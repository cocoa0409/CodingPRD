"""Business logic: calculations, inventory recompute, donor levels, serialization,
pagination, and input validation helpers.

Monetary precision (PRD §2.6): integer cents only; fractional factors are floored
(truncate toward zero) at the precise point each calculation specifies. We use
decimal.Decimal to avoid float drift, then floor with ROUND_FLOOR.
"""
from decimal import Decimal, ROUND_FLOOR

from db import store, parse_iso
from errors import err, ERR_VALIDATION

# --- pricing constants (PRD §3.5 / §3.3 / §3.7 / §3.6) ---
TIER_BASE_CENTS = {"PREMIUM": 9000, "STANDARD": 6000, "VALUE": 3500}
DONOR_DISCOUNT_PCT = {"NONE": "0.0", "FRIEND": "0.05", "PATRON": "0.10", "BENEFACTOR": "0.20"}
TIER_WEIGHT = {"PREMIUM": "1.5", "STANDARD": "1.0", "VALUE": "0.6"}
PAID_EXCHANGE_FEE_CENTS = 800
FLEX_PASS_NONSUB_FEE_CENTS = 500
FRIEND_MIN = 25000
PATRON_MIN = 100000
BENEFACTOR_MIN = 500000

# Default lifetime of an unpaid HELD ticket before it may be swept (logical-clock
# minutes). The PRD does not pin a number; a generous window keeps mid-flow holds
# alive while still allowing an explicit clock advance to expire them.
HOLD_TTL_MINUTES = 15


def floor_cents(value):
    """Floor a Decimal/number to integer cents (truncate toward zero == floor for
    non-negative monetary amounts)."""
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------
def body_or_400():
    from flask import request
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise err(ERR_VALIDATION, "Request body is not valid JSON")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err(ERR_VALIDATION, "Request body must be a JSON object")
        return data
    return {}


def req_str(body, key):
    if key not in body or not isinstance(body[key], str) or body[key] == "":
        raise err(ERR_VALIDATION, f"'{key}' is required and must be a non-empty string")
    return body[key]


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    if not isinstance(body[key], str):
        raise err(ERR_VALIDATION, f"'{key}' must be a string")
    return body[key]


def req_int(body, key, min_value=None, max_value=None):
    if key not in body:
        raise err(ERR_VALIDATION, f"'{key}' is required")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_VALIDATION, f"'{key}' must be an integer")
    if min_value is not None and v < min_value:
        raise err(ERR_VALIDATION, f"'{key}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err(ERR_VALIDATION, f"'{key}' must be <= {max_value}")
    return v


def opt_int(body, key, default=None, min_value=None, max_value=None):
    if key not in body or body[key] is None:
        return default
    return req_int(body, key, min_value=min_value, max_value=max_value)


def req_number(body, key, min_value=None, max_value=None):
    if key not in body:
        raise err(ERR_VALIDATION, f"'{key}' is required")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_VALIDATION, f"'{key}' must be a number")
    if min_value is not None and v < min_value:
        raise err(ERR_VALIDATION, f"'{key}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err(ERR_VALIDATION, f"'{key}' must be <= {max_value}")
    return v


def opt_number(body, key, default=None, min_value=None, max_value=None):
    if key not in body or body[key] is None:
        return default
    return req_number(body, key, min_value=min_value, max_value=max_value)


def opt_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    if not isinstance(body[key], bool):
        raise err(ERR_VALIDATION, f"'{key}' must be a boolean")
    return body[key]


def req_enum(body, key, choices):
    v = req_str(body, key)
    if v not in choices:
        raise err(ERR_VALIDATION, f"'{key}' must be one of {sorted(choices)}")
    return v


def opt_enum(body, key, choices, default=None):
    if key not in body or body[key] is None:
        return default
    return req_enum(body, key, choices)


def req_iso(body, key):
    v = req_str(body, key)
    try:
        parse_iso(v)
    except Exception:
        raise err(ERR_VALIDATION, f"'{key}' must be a valid ISO 8601 instant")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10 min 1 max 100; offset default 0.
# ---------------------------------------------------------------------------
def paginate(items):
    from flask import request

    def parse_pos(name, default, lo, hi):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, f"'{name}' must be an integer")
        if lo is not None and v < lo:
            raise err(ERR_VALIDATION, f"'{name}' must be >= {lo}")
        if hi is not None and v > hi:
            raise err(ERR_VALIDATION, f"'{name}' must be <= {hi}")
        return v

    limit = parse_pos("limit", 10, 1, 100)
    offset = parse_pos("offset", 0, 0, None)
    total = len(items)
    window = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, pagination


def sorted_by_created(values):
    # PRD §2.3: list endpoints sort by created_at ascending. created_at strings
    # share a fixed-width format so lexical order == chronological; ties broken by id.
    return sorted(values, key=lambda o: (o["created_at"], o["id"]))


# ---------------------------------------------------------------------------
# Donor level + lifetime donation (PRD §3.6)
# ---------------------------------------------------------------------------
def recompute_donor(patron):
    lifetime = sum(
        d["amount_cents"]
        for d in store.donations.values()
        if d["patron_id"] == patron["id"] and d["status"] == "FULFILLED"
    )
    patron["lifetime_donation_cents"] = lifetime
    if lifetime >= BENEFACTOR_MIN:
        level = "BENEFACTOR"
    elif lifetime >= PATRON_MIN:
        level = "PATRON"
    elif lifetime >= FRIEND_MIN:
        level = "FRIEND"
    else:
        level = "NONE"
    patron["donor_level"] = level


# ---------------------------------------------------------------------------
# Performance inventory (PRD §2.8 / §3 performance_inventory)
# ---------------------------------------------------------------------------
def recompute_inventory(perf):
    pid = perf["id"]
    held = 0
    sold = 0
    gross = 0
    for t in store.tickets.values():
        if t["performance_id"] != pid:
            continue
        if t["fulfillment_status"] == "HELD":
            held += 1
        elif t["fulfillment_status"] in ("ISSUED", "COLLECTED"):
            sold += 1
        if t["payment_status"] == "PAID":
            gross += t["price_cents"]
    perf["held_seat_count"] = held
    perf["sold_seat_count"] = sold
    cap = perf.get("capacity")
    if cap is None:
        perf["available_seat_count"] = None
    else:
        perf["available_seat_count"] = max(0, cap - held - sold)
    perf["gross_sales_cents"] = gross


# ---------------------------------------------------------------------------
# Pricing calculations
# ---------------------------------------------------------------------------
def single_ticket_price(seat, performance, patron):
    """PRD §3.5: floor(tier_base * demand * (1 - donor_pct)); demand first, then
    donor discount, then floor."""
    tier_base = Decimal(TIER_BASE_CENTS[seat["price_tier"]])
    demand = Decimal(str(performance["demand_multiplier"]))
    donor_pct = Decimal(DONOR_DISCOUNT_PCT[patron["donor_level"]])
    raw = tier_base * demand
    discounted = raw * (Decimal("1") - donor_pct)
    return floor_cents(discounted)


def subscription_price_per_seat(seat, season, is_renewal):
    """PRD §3.3: per_seat = floor(base * tier_weight); if renewal, floor(per_seat *
    (1 - loyalty_renewal_discount_pct)). Floor per seat is the pinned boundary."""
    base = Decimal(season["base_subscription_fee_cents"])
    weight = Decimal(TIER_WEIGHT[seat["price_tier"]])
    per_seat = floor_cents(base * weight)
    if is_renewal:
        disc = Decimal(str(season["loyalty_renewal_discount_pct"]))
        per_seat = floor_cents(Decimal(per_seat) * (Decimal("1") - disc))
    return per_seat


def price_subscription(subscription):
    """Run subscription_pricing across ASSIGNED seats: floor-per-seat THEN sum."""
    season = store.seasons[subscription["season_id"]]
    is_renewal = subscription["is_renewal"]
    total = 0
    for ss in store.subscription_seats.values():
        if ss["subscription_id"] != subscription["id"] or ss["status"] != "ASSIGNED":
            continue
        seat = store.seats[ss["seat_id"]]
        per_seat = subscription_price_per_seat(seat, season, is_renewal)
        ss["per_seat_price_cents"] = per_seat
        store.touch(ss)
        total += per_seat
    subscription["total_price_cents"] = total


def exchange_fee(exchange, original_ticket, target_single_price):
    """PRD §3.7: price_delta floored at 0; fee per mode; total = fee + delta."""
    price_delta = max(0, target_single_price - original_ticket["price_cents"])
    if exchange["mode"] == "FLEX_PASS":
        if original_ticket["origin"] == "SUBSCRIPTION":
            fee = 0
        else:
            fee = FLEX_PASS_NONSUB_FEE_CENTS
    else:  # PAID_EXCHANGE
        fee = PAID_EXCHANGE_FEE_CENTS
    total = fee + price_delta
    return fee, price_delta, total

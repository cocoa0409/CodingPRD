"""Business logic: calculations, state transitions, cascades.

All money is integer cents. Rounding: round-half-up via Decimal.
avg_daily_usage: 4 decimal places, round half up.
"""
import math
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from errors import (
    ApiError, ERR_VALIDATION, ERR_INSUFFICIENT_STOCK, ERR_CREDIT_LIMIT_EXCEEDED,
)

# ---- Calculation constants (SCAFFOLD calculations[].constants) ----
FORECAST_WINDOW_DAYS = 90
LEAD_TIME_DAYS = 7
DELIVERY_MINIMUM_CENTS = 5000
FUEL_INDEX_TIER_LOW = Decimal("3.00")
FUEL_INDEX_TIER_HIGH = Decimal("4.00")
DIST_BAND_MID = 25
DIST_BAND_HIGH = 75
PASS_SCORE_PCT = 80
TRAINING_VALIDITY_DAYS = 365
PROPOSAL_TTL_DAYS = 7

FREQUENCY_DAYS = {"WEEKLY": 7, "BIWEEKLY": 14, "MONTHLY": 30}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def base_resource():
    """Common fields present on every resource."""
    ts = clock.iso_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Refresh updated_at and increment version on a mutation."""
    entity["updated_at"] = clock.iso_now()
    entity["version"] = entity.get("version", 1) + 1


def round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value: Decimal) -> float:
    q = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Facility ledger (credit_exposure)
# ---------------------------------------------------------------------------

def recompute_facility_ledger(facility):
    committed = 0
    outstanding = 0
    for o in db.orders.values():
        if o["facility_id"] != facility["id"]:
            continue
        if o["status"] in ("PLACED", "PARTIALLY_BLOCKED", "DELIVERED"):
            committed += o["total_cents"]
        elif o["status"] == "INVOICED":
            outstanding += o["total_cents"]
    if facility["committed_cents"] != committed or facility["outstanding_cents"] != outstanding:
        facility["committed_cents"] = committed
        facility["outstanding_cents"] = outstanding
        touch(facility)


def recompute_closed_loop(facility):
    enrolled = any(
        d["facility_id"] == facility["id"] and d["status"] == "INSTALLED"
        for d in db.dispensers.values()
    )
    if facility["closed_loop_enrolled"] != enrolled:
        facility["closed_loop_enrolled"] = enrolled
        touch(facility)


# ---------------------------------------------------------------------------
# Effective unit price (§3.8)
# ---------------------------------------------------------------------------

def effective_unit_price(facility, product, at_time):
    candidates = []
    for bid in db.contract_bids.values():
        if bid["status"] != "AWARDED":
            continue
        if bid["facility_group_code"] != facility["facility_group_code"]:
            continue
        ps = clock.parse_iso(bid["protection_start"])
        pe = clock.parse_iso(bid["protection_end"])
        # CLOSED interval [protection_start, protection_end]
        if not (ps <= at_time <= pe):
            continue
        for line in bid["lines"]:
            if line["product_id"] == product["id"]:
                candidates.append(bid)
                break
    if not candidates:
        return product["base_price_cents"]

    def bid_line_price(bid):
        for line in bid["lines"]:
            if line["product_id"] == product["id"]:
                return line["bid_price_cents"]
        return None

    candidates.sort(key=lambda b: (
        bid_line_price(b),
        clock.parse_iso(b["protection_start"]),
        clock.parse_iso(b["created_at"]),
    ))
    return bid_line_price(candidates[0])


# ---------------------------------------------------------------------------
# Order pricing (order_line_pricing / order_total_rollup / fuel_surcharge)
# ---------------------------------------------------------------------------

def order_lines_of(order):
    return [l for l in db.order_lines.values() if l["order_id"] == order["id"]]


def compute_line_total(line):
    qty = Decimal(line["qty"])
    price = Decimal(line["unit_price_cents"])
    discount = Decimal(str(line["discount_pct"]))
    raw = qty * price * (Decimal(1) - discount)
    return round_half_up_cents(raw)


def fuel_pct(fuel_index) -> Decimal:
    fi = Decimal(str(fuel_index))
    if fi < FUEL_INDEX_TIER_LOW:
        return Decimal("0.04")
    if fi < FUEL_INDEX_TIER_HIGH:
        return Decimal("0.06")
    return Decimal("0.09")


def dist_mult(miles) -> Decimal:
    m = Decimal(str(miles))
    if m < DIST_BAND_MID:
        return Decimal("1.0")
    if m < DIST_BAND_HIGH:
        return Decimal("1.25")
    return Decimal("1.5")


def compute_fuel_surcharge(base_cents: int, fuel_index, miles) -> int:
    pct = fuel_pct(fuel_index)
    mult = dist_mult(miles)
    return round_half_up_cents(Decimal(base_cents) * pct * mult)


def recompute_order_money(order, fuel_index=None):
    """Recompute merchandise subtotal, delivery fee, surcharge, total.
    Cancelled lines contribute 0 (excluded from sum).
    If fuel_index is None, use order.fuel_index (QUOTED)."""
    subtotal = 0
    for line in order_lines_of(order):
        if line["status"] == "CANCELLED":
            continue
        subtotal += line["line_total_cents"]
    order["merchandise_subtotal_cents"] = subtotal
    order["delivery_fee_cents"] = max(0, DELIVERY_MINIMUM_CENTS - subtotal)
    base = subtotal + order["delivery_fee_cents"]
    facility = db.facilities.get(order["facility_id"])
    miles = facility["delivery_distance_miles"] if facility else 0
    idx = order["fuel_index"] if fuel_index is None else fuel_index
    order["fuel_surcharge_cents"] = compute_fuel_surcharge(base, idx, miles)
    total = subtotal + order["delivery_fee_cents"] + order["fuel_surcharge_cents"] - order["trial_credit_cents"]
    order["total_cents"] = max(0, total)


# ---------------------------------------------------------------------------
# Order auto-transitions (§3.6/§3.7)
# ---------------------------------------------------------------------------

def auto_transition_order(order):
    """After line mutations: recompute money, apply auto state transitions,
    and resync the facility ledger. Returns True if order mutated."""
    lines = order_lines_of(order)
    if order["status"] not in ("PLACED", "PARTIALLY_BLOCKED"):
        return False
    recompute_order_money(order)
    all_cancelled = all(l["status"] == "CANCELLED" for l in lines) if lines else False
    any_sub_pending = any(l["status"] == "SUBSTITUTION_PENDING" for l in lines)
    any_active_line = any(l["status"] in ("ALLOCATED", "FULFILLED") for l in lines)

    if all_cancelled and lines:
        order["status"] = "CANCELLED"
        touch(order)
        facility = db.facilities.get(order["facility_id"])
        if facility:
            recompute_facility_ledger(facility)
        return True
    if order["status"] == "PLACED" and any_sub_pending:
        order["status"] = "PARTIALLY_BLOCKED"
        touch(order)
        facility = db.facilities.get(order["facility_id"])
        if facility:
            recompute_facility_ledger(facility)
        return True
    if order["status"] == "PARTIALLY_BLOCKED" and not any_sub_pending and any_active_line:
        order["status"] = "PLACED"
        touch(order)
        facility = db.facilities.get(order["facility_id"])
        if facility:
            recompute_facility_ledger(facility)
        return True
    # No state change, but money was recomputed
    touch(order)
    facility = db.facilities.get(order["facility_id"])
    if facility:
        recompute_facility_ledger(facility)
    return True


# ---------------------------------------------------------------------------
# Substitute selector (§3.7)
# ---------------------------------------------------------------------------

def select_substitute(original_product):
    candidates = [
        p for p in db.products.values()
        if p["status"] == "ACTIVE"
        and p["category"] == original_product["category"]
        and p["id"] != original_product["id"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["base_price_cents"], clock.parse_iso(p["created_at"])))
    return candidates[0]


def run_shortage_cascade(product):
    """declare-shortage cascade: lines -> proposals -> orders -> facility."""
    affected_orders = {}
    for line in list(db.order_lines.values()):
        if line["product_id"] != product["id"]:
            continue
        if line["status"] not in ("PENDING", "ALLOCATED"):
            continue
        order = db.orders.get(line["order_id"])
        facility = db.facilities.get(order["facility_id"]) if order else None
        # ALLOCATED lines release reservation first
        if line["status"] == "ALLOCATED":
            product["qty_allocated"] -= line["qty"]
            product["qty_on_hand"] += line["qty"]
        substitute = select_substitute(product)
        if substitute is not None:
            line["status"] = "SUBSTITUTION_PENDING"
            touch(line)
            # Proposal
            prop = base_resource()
            orig_price = effective_unit_price(facility, product, clock.now()) if facility else product["base_price_cents"]
            prop_price = effective_unit_price(facility, substitute, clock.now()) if facility else substitute["base_price_cents"]
            prop.update({
                "order_line_id": line["id"],
                "original_product_id": product["id"],
                "proposed_product_id": substitute["id"],
                "price_delta_cents": (prop_price - orig_price) * line["qty"],
                "status": "PENDING",
                "expires_at": clock.iso_format(clock.now() + timedelta(days=PROPOSAL_TTL_DAYS)),
            })
            db.substitution_proposals[prop["id"]] = prop
        else:
            line["status"] = "CANCELLED"
            touch(line)
        if order:
            affected_orders[order["id"]] = order
    for order in affected_orders.values():
        auto_transition_order(order)


# ---------------------------------------------------------------------------
# Usage forecast (§3.3)
# ---------------------------------------------------------------------------

def recompute_forecast(profile, variant: str):
    now = clock.now()
    window_start = now - timedelta(days=FORECAST_WINDOW_DAYS)
    total = 0
    for rec in db.usage_records.values():
        if rec["facility_id"] != profile["facility_id"]:
            continue
        if rec["product_id"] != profile["product_id"]:
            continue
        if variant == "FINAL":
            if rec["status"] != "POSTED":
                continue
        else:  # PROVISIONAL includes SUBMITTED + POSTED
            if rec["status"] not in ("SUBMITTED", "POSTED"):
                continue
        pe = clock.parse_iso(rec["period_end"])
        if pe is None:
            continue
        if window_start <= pe <= now:
            total += rec["quantity_used"]
    avg = round_half_up_4dp(Decimal(total) / Decimal(FORECAST_WINDOW_DAYS))
    profile["avg_daily_usage"] = avg
    profile["reorder_point"] = math.ceil(Decimal(str(avg)) * LEAD_TIME_DAYS) + profile["safety_stock"]
    horizon_demand = math.ceil(Decimal(str(avg)) * profile["horizon_days"])
    profile["recommended_qty"] = max(0, horizon_demand - profile["current_on_hand"])
    profile["replenishment_recommended"] = profile["current_on_hand"] <= profile["reorder_point"]
    profile["variant_used"] = variant
    profile["last_computed_at"] = clock.iso_now()
    touch(profile)


# ---------------------------------------------------------------------------
# Standing order preview (§3.5)
# ---------------------------------------------------------------------------

def recompute_standing_order_preview(so):
    facility = db.facilities.get(so["facility_id"])
    now = clock.now()
    total = 0
    protected = False
    for item in so["items"]:
        product = db.products.get(item["product_id"])
        if product is None or facility is None:
            continue
        price = effective_unit_price(facility, product, now)
        total += item["qty"] * price
        # price_protected: >=1 item covered by an AWARDED bid matching group
        for bid in db.contract_bids.values():
            if bid["status"] != "AWARDED":
                continue
            if bid["facility_group_code"] != facility["facility_group_code"]:
                continue
            ps = clock.parse_iso(bid["protection_start"])
            pe = clock.parse_iso(bid["protection_end"])
            if not (ps <= now <= pe):
                continue
            if any(l["product_id"] == product["id"] for l in bid["lines"]):
                protected = True
                break
    so["next_delivery_total_cents"] = total
    so["price_protected"] = protected


def cascade_bid_to_standing_orders(bid):
    """On award/terminate/expire: recompute affected standing orders."""
    for so in db.standing_orders.values():
        if so["status"] not in ("ACTIVE", "PAUSED"):
            continue
        facility = db.facilities.get(so["facility_id"])
        if facility is None:
            continue
        if facility["facility_group_code"] != bid["facility_group_code"]:
            continue
        recompute_standing_order_preview(so)
        touch(so)


# ---------------------------------------------------------------------------
# Order placement pipeline (§3.6) — shared by place, trial convert, sweep
# ---------------------------------------------------------------------------

def place_order(order, from_trial=False):
    """Run the full placement pipeline. Raises ApiError on validation failure.
    Caller must have already validated order.status == DRAFT (for manual place)."""
    facility = db.facilities.get(order["facility_id"])
    # facility gate is validated by callers before invoking (priority 8)
    lines = order_lines_of(order)

    # priority 9: every line product ACTIVE
    for line in lines:
        product = db.products.get(line["product_id"])
        if product is None or product["status"] != "ACTIVE":
            raise ApiError("ERR_PRODUCT_UNAVAILABLE", "Line product is not ACTIVE", 409)

    # priority 10: stock sufficiency (all-or-nothing)
    for line in lines:
        product = db.products.get(line["product_id"])
        if product["qty_on_hand"] < line["qty"]:
            raise ApiError(ERR_INSUFFICIENT_STOCK, "Insufficient stock for line", 409)

    # priority 11: dilution training
    for line in lines:
        product = db.products.get(line["product_id"])
        if product["dilution_required"]:
            certified = any(
                t["facility_id"] == order["facility_id"]
                and t["product_id"] == product["id"]
                and t["status"] == "CERTIFIED"
                for t in db.training_records.values()
            )
            if not certified:
                raise ApiError("ERR_TRAINING_NOT_CERTIFIED",
                               "Dilution-required chemical lacks CERTIFIED training record", 409)

    # Freeze prices and compute money
    now = clock.now()
    for line in lines:
        product = db.products.get(line["product_id"])
        line["unit_price_cents"] = effective_unit_price(facility, product, now)
        line["line_total_cents"] = compute_line_total(line)
    recompute_order_money(order)  # QUOTED variant uses order.fuel_index

    # priority 20: credit check
    if facility["committed_cents"] + order["total_cents"] > facility["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, "Credit limit exceeded", 409)

    # Commit: allocate stock, transition lines, stamp order
    for line in lines:
        product = db.products.get(line["product_id"])
        product["qty_on_hand"] -= line["qty"]
        product["qty_allocated"] += line["qty"]
        line["status"] = "ALLOCATED"
        touch(line)
    order["fuel_surcharge_variant"] = "QUOTED"
    order["placed_at"] = clock.iso_now()
    order["status"] = "PLACED"
    touch(order)
    recompute_facility_ledger(facility)


# ---------------------------------------------------------------------------
# Validation helpers for request payloads
# ---------------------------------------------------------------------------

def require_field(body, name):
    if body is None or name not in body or body[name] is None:
        raise ApiError(ERR_VALIDATION, "Missing required field: %s" % name, 400)
    return body[name]


def as_int(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_VALIDATION, "Field %s must be an integer" % name, 400)
    if minimum is not None and value < minimum:
        raise ApiError(ERR_VALIDATION, "Field %s must be >= %s" % (name, minimum), 400)
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_VALIDATION, "Field %s must be a number" % name, 400)
    return value


def as_str(value, name):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, "Field %s must be a string" % name, 400)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(ERR_VALIDATION, "Field %s must be one of %s" % (name, ", ".join(allowed)), 400)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError(ERR_VALIDATION, "Field %s must be a boolean" % name, 400)
    return value


def as_datetime(value, name):
    dt = clock.parse_iso(value)
    if dt is None:
        raise ApiError(ERR_VALIDATION, "Field %s must be an ISO 8601 datetime" % name, 400)
    return dt

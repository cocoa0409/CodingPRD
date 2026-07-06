"""Calculations, clock helpers, validation helpers, serialization, pagination.

Every rule here traces to a verbatim PRD sentence (section refs inline).
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Rounding: "round half up, applied exactly once at the point the spec names"
# (PRD §2.6).
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    """value is a Decimal or numeric; return integer cents rounded half up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Logical clock (PRD §3.10)
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    if not isinstance(s, str):
        raise err("ERR_VALIDATION", "Invalid timestamp")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise err("ERR_VALIDATION", "Invalid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_dt(db):
    return parse_iso(db.clock)


def epoch_seconds(dt):
    return dt.timestamp()


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require_field(body, name, types):
    if name not in body or body[name] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {name}")
    val = body[name]
    if not _type_ok(val, types):
        raise err("ERR_VALIDATION", f"Field {name} has the wrong type")
    return val


def optional_field(body, name, types, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not _type_ok(val, types):
        raise err("ERR_VALIDATION", f"Field {name} has the wrong type")
    return val


def _type_ok(val, types):
    # bool is a subclass of int; guard so int fields reject booleans and vice versa.
    if types == "bool":
        return isinstance(val, bool)
    if types == "int":
        return isinstance(val, int) and not isinstance(val, bool)
    if types == "number":
        return (isinstance(val, (int, float)) and not isinstance(val, bool))
    if types == "str":
        return isinstance(val, str)
    if types == "int_or_float":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    raise RuntimeError("unknown type spec")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ascending, apply limit/offset, return (page, meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# calculations.surgical_risk_score (PRD §3.1)
# ---------------------------------------------------------------------------
def compute_risk(patient):
    asa = patient["asa_class"]
    bmi = patient["bmi"]
    smoker = patient["smoker"]
    age = patient["age_years"]
    prior = patient["prior_complication_count"]

    score = (asa - 1) * 25
    if bmi >= 35:
        score += 20
    elif bmi >= 30:
        score += 10
    if smoker:
        score += 20
    if age >= 65:
        score += 15
    elif age >= 50:
        score += 8
    score += prior * 15
    score = max(0, min(100, score))

    if score >= 70:
        tier = "MEDICAL"
    elif score >= 40:
        tier = "STANDARD"
    else:
        tier = "NONE"

    patient["surgical_risk_score"] = score
    patient["clearance_tier"] = tier


# ---------------------------------------------------------------------------
# calculations.line_bundle + quote_total + required_deposit (PRD §3.3)
# ---------------------------------------------------------------------------
def recompute_quote_pricing(quote, line_items):
    """Recompute subtotal/discount/total/required_deposit while DRAFT."""
    lines = [li for li in line_items if li["quote_package_id"] == quote["id"]]
    subtotal = sum(li["bundle_total_cents"] for li in lines)
    n = len(lines)
    if n >= 3:
        discount = 0.10
    elif n == 2:
        discount = 0.05
    else:
        discount = 0.00
    quote["subtotal_cents"] = subtotal
    quote["discount_pct"] = discount
    # SUM first, THEN apply discount, THEN round_half_up once.
    total = round_half_up_cents(Decimal(subtotal) * (Decimal(1) - Decimal(str(discount))))
    quote["total_cents"] = total
    quote["required_deposit_cents"] = round_half_up_cents(
        Decimal(total) * Decimal("0.20")
    )


def recompute_balance(quote):
    """balance_due = total - deposit_paid - financed (PRD §2.6)."""
    quote["balance_due_cents"] = (
        quote["total_cents"] - quote["deposit_paid_cents"] - quote["financed_cents"]
    )


# ---------------------------------------------------------------------------
# calculations.cancellation_settlement (PRD §3.7)
# ---------------------------------------------------------------------------
def cancellation_settlement(deposit_paid_cents, scheduled_start_dt, clock):
    delta_seconds = epoch_seconds(scheduled_start_dt) - epoch_seconds(clock)
    import math
    days_notice = math.floor(delta_seconds / SECONDS_PER_DAY)
    if days_notice >= 30:
        refund_pct = Decimal("1.00")
    elif days_notice >= 14:
        refund_pct = Decimal("0.50")
    else:
        refund_pct = Decimal("0.00")
    refunded = round_half_up_cents(Decimal(deposit_paid_cents) * refund_pct)
    forfeited = deposit_paid_cents - refunded
    return refunded, forfeited


# ---------------------------------------------------------------------------
# calculations.practice_net (PRD §3.8)
# ---------------------------------------------------------------------------
def practice_net(approved_amount_cents, lender):
    if lender == "CHERRY":
        fee = round_half_up_cents(Decimal(approved_amount_cents) * Decimal("0.05"))
    elif lender == "CARECREDIT":
        fee = round_half_up_cents(Decimal(approved_amount_cents) * Decimal("0.03"))
    else:
        fee = 0
    net = approved_amount_cents - fee
    return fee, net


# ---------------------------------------------------------------------------
# calculations.revision_charge (PRD §3.9)
# ---------------------------------------------------------------------------
def revision_charge(case, booking, procedure, line_item):
    window_days = procedure["revision_window_days"]
    reported = parse_iso(case["reported_at"])
    scheduled_end = parse_iso(booking["scheduled_end"])
    window_end = epoch_seconds(scheduled_end) + window_days * SECONDS_PER_DAY
    within = epoch_seconds(reported) <= window_end
    if case["attribution"] == "SURGICAL_ORIGIN" and within:
        charge = 0
    else:
        charge = round_half_up_cents(
            Decimal(line_item["surgical_fee_cents"]) * Decimal("0.50")
        )
    return within, charge


# ---------------------------------------------------------------------------
# Clearance tier satisfaction (PRD §3.5)
# ---------------------------------------------------------------------------
_TIER_RANK = {"NONE": 0, "STANDARD": 1, "MEDICAL": 2}


def tier_satisfies(provided, required):
    return _TIER_RANK[provided] >= _TIER_RANK[required]

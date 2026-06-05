"""Merit and equity calculations for CompPlan."""
import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from db import db
from routes.cycles import bands_for_cycle

PROMO_UPLIFT_PER_BAND = Decimal("0.03")
MERIT_PCT_CAP = Decimal("0.25")

MIN_TENURE_YEARS = 1
TENURE_STEP = Decimal("0.10")
TENURE_CAP_YEARS = 5
BAND_EQUITY_FACTOR = {"EXCEEDS": Decimal("400"), "MEETS": Decimal("150"), "BELOW": Decimal("0")}


def _band_for_label(cycle_id, label):
    for b in bands_for_cycle(cycle_id):
        if b["label"] == label:
            return b
    return None


def _parse_dt(value):
    if isinstance(value, str):
        v = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            # date-only string
            return datetime.fromisoformat(v.split("T")[0])
    raise ValueError("invalid datetime")


def tenure_years(cycle, employee):
    hire = _parse_dt(employee["hire_date"])
    created = _parse_dt(cycle["created_at"])
    # Make both naive for subtraction if mismatched tz-awareness.
    if hire.tzinfo is not None and created.tzinfo is None:
        created = created.replace(tzinfo=hire.tzinfo)
    if created.tzinfo is not None and hire.tzinfo is None:
        hire = hire.replace(tzinfo=created.tzinfo)
    days = (created - hire).days
    return days // 365


def compute_merit(cycle_id, review, plan_type, promo_band_jump):
    """Return (merit_pct, merit_amount) as floats."""
    band = _band_for_label(cycle_id, review["final_rating"])
    base_pct = Decimal(str(band["merit_pct"])) if band else Decimal("0")
    if plan_type == "MERIT_AND_PROMO":
        uplift = PROMO_UPLIFT_PER_BAND * Decimal(promo_band_jump)
        merit_pct = min(base_pct + uplift, MERIT_PCT_CAP)
    else:
        merit_pct = base_pct
    amount = (merit_pct * Decimal(str(review["base_salary"]))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(merit_pct), float(amount)


def compute_equity(cycle, review):
    """Return equity_refresh_units (float). Pool-clamped against current committed."""
    employee = db.employees[review["employee_id"]]
    ty = tenure_years(cycle, employee)
    if ty < MIN_TENURE_YEARS:
        return 0.0
    band_factor = BAND_EQUITY_FACTOR.get(review["final_rating"], Decimal("0"))
    capped_tenure = min(ty, TENURE_CAP_YEARS)
    raw_target = band_factor * (Decimal("1") + TENURE_STEP * Decimal(capped_tenure))
    remaining = Decimal(str(cycle["equity_refresh_pool"])) - \
        Decimal(str(cycle["equity_committed_total"]))
    granted = min(raw_target, remaining)
    if granted < 0:
        granted = Decimal("0")
    return float(granted.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))

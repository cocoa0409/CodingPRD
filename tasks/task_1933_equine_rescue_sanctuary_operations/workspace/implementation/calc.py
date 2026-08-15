"""Calculation rules (scaffold 1.3 / PRD section 3).

All monetary rounding is round-half-up to integer cents; feed weights carry
two decimals; the daily ration carries one decimal. Intermediates stay
unrounded unless a rule pins a rounding step.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err, ERR_INVALID_REQUEST

D = Decimal


def rhu(value, places):
    """Round half up a Decimal to the given number of decimal places."""
    return value.quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to integer, returned as int."""
    return int(value.quantize(D("1"), rounding=ROUND_HALF_UP))


def dec_num(value):
    """Decimal from a JSON number without float artifacts."""
    return D(str(value))


# --------------------------------------------------------------------------
# daily_feed_ration
# --------------------------------------------------------------------------
def daily_ration(weight_lbs, bcs):
    w = D(weight_lbs)
    base = w * D("0.02")
    if bcs <= 3:
        base = base * D("1.30")
    elif bcs >= 7:
        base = base * D("0.80")
    base = min(base, w * D("0.025"))
    base = max(base, D("4.0"))
    return rhu(base, 1)


# --------------------------------------------------------------------------
# lifetime_care_cost_projection
# --------------------------------------------------------------------------
LIFESPAN_YEARS = {"LIGHT": 25, "DRAFT": 22, "PONY": 28}
MONTHLY_BASE_CENTS = 38500


def _band_cost(age):
    if age < 15:
        return 38500
    if age < 20:
        return 45200
    if age < 25:
        return 52800
    return 61500


def _annual_survival(age):
    if age < 20:
        return 0.97
    if age < 25:
        return 0.89
    return 0.78


def care_projection(breed_class, age_years, variant):
    """Returns (projected_months, monthly_cost_cents, total_lifetime_cost_cents)."""
    months = (LIFESPAN_YEARS[breed_class] - age_years) * 12
    if months <= 0:
        raise_err(
            ERR_INVALID_REQUEST,
            "Projected lifespan months must be positive for this horse",
        )
    if variant == "STRAIGHT_LINE":
        return months, MONTHLY_BASE_CENTS, months * MONTHLY_BASE_CENTS

    # ACTUARIAL: month-by-month walk, intermediates unrounded.
    total_raw = 0.0
    survival = 1.0
    for m in range(1, months + 1):
        age_at_month = age_years + (m - 1) / 12.0
        survival = survival * (_annual_survival(age_at_month) ** (1.0 / 12.0))
        total_raw += _band_cost(age_at_month) * survival
    total = rhu_int(D(repr(total_raw)))
    monthly = rhu_int(D(total) / D(months))
    return months, monthly, total


# --------------------------------------------------------------------------
# adoption_fee_calculation (QUOTED and FINAL variants share these steps)
# --------------------------------------------------------------------------
def _base_fee(horse):
    age = horse["age_years"]
    if age < 2:
        fee = 95000
    elif age <= 14:
        fee = 85000
    elif age <= 19:
        fee = 60000
    else:
        fee = 35000
    tl = horse["training_level"]
    if tl == "TRAINED_RIDDEN":
        fee += 15000
    elif tl == "GREEN":
        fee -= 10000
    elif tl == "UNHANDLED":
        fee -= 20000
    has_completed_plan = any(
        p["horse_id"] == horse["id"] and p["status"] == "COMPLETED"
        for p in db.rehab_plans.values()
    )
    if has_completed_plan:
        fee += 5000
    return fee


def adoption_fee(primary_horse, pair_flag):
    """Pinned order: (1) base+adjustments, (2) pair rule, (3) sponsor subsidy."""
    fee = D(_base_fee(primary_horse))
    if pair_flag:
        companion = db.horses.get(primary_horse["bonded_companion_id"])
        if companion is not None:
            fee = fee + D(_base_fee(companion))
        fee = D(rhu_int(fee * D("0.75")))
    active_pledge_sum = sum(
        s["monthly_pledge_cents"]
        for s in db.sponsorships.values()
        if s["horse_id"] == primary_horse["id"] and s["status"] == "ACTIVE"
    )
    if active_pledge_sum >= 19250:
        fee = D(rhu_int(fee * D("0.90")))
    return rhu_int(fee)


# --------------------------------------------------------------------------
# feed_supply_projection helpers
# --------------------------------------------------------------------------
FEED_TYPES = ("GRASS_HAY", "ALFALFA", "GRAIN", "SUPPLEMENT")
RESIDENT_STATUSES = {
    "QUARANTINE",
    "REHABILITATION",
    "ADOPTABLE",
    "ADOPTION_PENDING",
    "SANCTUARY",
    "END_OF_LIFE_REVIEW",
}


def seasonal_multiplier(month):
    if month in (12, 1, 2):
        return D("1.25")
    if month in (3, 4, 5):
        return D("1.00")
    if month in (6, 7, 8):
        return D("0.90")
    return D("1.10")


def daily_demand():
    """Exact (unrounded) per-feed-type daily demand over resident horses."""
    demand = {ft: D("0") for ft in FEED_TYPES}
    for h in db.horses.values():
        if h["status"] not in RESIDENT_STATUSES:
            continue
        ration = h["daily_feed_ration_lbs"]  # Decimal, 1dp
        hay = ration * D("0.70")
        if h["body_condition_score"] <= 3:
            demand["GRASS_HAY"] += hay * D("0.50")
            demand["ALFALFA"] += hay * D("0.50")
        else:
            demand["GRASS_HAY"] += hay
        demand["GRAIN"] += ration * D("0.20")
        demand["SUPPLEMENT"] += ration * D("0.10")
    return demand


# --------------------------------------------------------------------------
# purchase_order_cost
# --------------------------------------------------------------------------
def estimated_total(quantity_lbs, unit_cents_per_lb):
    return rhu_int(dec_num(quantity_lbs) * dec_num(unit_cents_per_lb))


def lot_cost(initial_lbs, unit_cents_per_lb):
    return rhu_int(dec_num(initial_lbs) * dec_num(unit_cents_per_lb))


def surcharge(actual_total_cents):
    return rhu_int(D(actual_total_cents) * D("0.08"))


# --------------------------------------------------------------------------
# volunteer_reliability
# --------------------------------------------------------------------------
def reliability(completed_shift_count, no_show_count):
    score = 50 + 5 * completed_shift_count - 20 * no_show_count
    return max(0, min(100, score))

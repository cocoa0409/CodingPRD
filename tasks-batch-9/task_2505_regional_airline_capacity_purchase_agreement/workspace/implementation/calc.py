"""The nine calculation rules of scaffold 1.3 / PRD 3.2-3.8."""

from decimal import Decimal, ROUND_FLOOR

from core import ZERO2, ZERO3, dec, round2, round3
from db import store, ordered

# --------------------------------------------------------------------- constants
ON_TIME_GRACE_MINUTES = 14
AIRCRAFT_MIN_TURN_MINUTES = 35
PILOT_ROLLING_BLOCK_CAP_HOURS = Decimal("16.000")
PILOT_ROLLING_WINDOW_HOURS = 24

ATTRITION_DISCOUNT = Decimal("0.35")
PIPELINE_CREDIT = Decimal("1") - ATTRITION_DISCOUNT  # 0.65

CF_TIER_HIGH_PCT = Decimal("99.00")
CF_TIER_MID_PCT = Decimal("97.50")
OTA_TIER_HIGH_PCT = Decimal("85.00")
OTA_TIER_MID_PCT = Decimal("80.00")
BAG_TIER_LOW_PER_1000 = Decimal("3.00")
BAG_TIER_MID_PER_1000 = Decimal("5.50")
POINT_VALUE_USD = Decimal("12000.00")
INCENTIVE_REVENUE_SHARE = Decimal("0.05")

ZERO_ELIGIBLE_RESULT_PCT = Decimal("100.00")
EMPTY_SET_RESULT_PCT = Decimal("100.00")
ZERO_BAGS_RESULT = Decimal("0.00")

SEVERITY_WEIGHT_USD = {
    "MINOR": Decimal("500.00"),
    "MAJOR": Decimal("2500.00"),
    "CRITICAL": Decimal("7500.00"),
}
BRAND_PENALTY_CAP_USD = Decimal("25000.00")

CATEGORY_TOLERANCE = {
    "FUEL": None,
    "AIRPORT_FEES": Decimal("0.10"),
    "INSURANCE": Decimal("0.05"),
}
ADMIN_TIER_1_USD = Decimal("100000.00")
ADMIN_TIER_2_USD = Decimal("500000.00")
ADMIN_FEE_TIER_LOW_RATE = Decimal("0.030")
ADMIN_FEE_TIER_MID_RATE = Decimal("0.020")
ADMIN_FEE_TIER_HIGH_RATE = Decimal("0.015")

MAX_DISPUTE_ROUNDS = 2
MAX_COUNTER_ROUNDS = 2

EXPOSED_FINDING_STATUSES = ("OPEN", "ACKNOWLEDGED")
EXPOSED_REMEDIATION_STATUSES = ("NOT_STARTED", "IN_PROGRESS")

FLEET_PAID_STATUSES = ("IN_SERVICE", "GROUNDED_STAFFING")


def _floor(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# ------------------------------------------------------- variable_flight_payment
def leg_variable_amount(hours, agreement):
    """Per-leg amount: round2(hours * block_hour_rate) + departure_rate (PRD 3.8)."""
    return round2(dec(hours) * agreement["block_hour_rate_usd"]) + \
        agreement["departure_rate_usd"]


def _leg_order(leg):
    return (leg["_scheduled_departure_dt"], leg["created_at"], leg["id"])


def included_legs(cycle_id, variant):
    legs = [leg for leg in store.flight_legs.values() if leg["cycle_id"] == cycle_id]
    if variant == "ACTUAL_BASIS":
        legs = [leg for leg in legs if leg["status"] == "COMPLETED"]
    else:
        legs = [leg for leg in legs if leg["status"] in ("SCHEDULED", "COMPLETED")]
    legs.sort(key=_leg_order)
    return legs


def variable_flight_payment(cycle, agreement, variant):
    """Sum of already-rounded per-leg amounts; the rounding order is pinned."""
    hours_field = ("actual_block_hours" if variant == "ACTUAL_BASIS"
                   else "planned_block_hours")
    total = ZERO2
    for leg in included_legs(cycle["id"], variant):
        hours = leg.get(hours_field)
        if hours is None:
            continue
        total += leg_variable_amount(hours, agreement)
    return round2(total)


# ----------------------------------------------------------------- fixed component
def ownership_aircraft_count(agreement_id):
    return sum(
        1
        for tail in store.aircraft.values()
        if tail["agreement_id"] == agreement_id
        and tail["ownership"] == "REGIONAL_OWNED"
        and tail["status"] in FLEET_PAID_STATUSES
    )


def fixed_component(agreement):
    count = ownership_aircraft_count(agreement["id"])
    amount = agreement["fixed_monthly_fee_usd"] + \
        round2(agreement["aircraft_ownership_fee_usd"] * count)
    return count, round2(amount)


# --------------------------------------------------------------- cycle metrics
def completion_factor(published_departures, uncontrollable, controllable):
    eligible = published_departures - uncontrollable
    if eligible <= 0:
        return ZERO_ELIGIBLE_RESULT_PCT
    return round2(Decimal(100) * Decimal(eligible - controllable) / Decimal(eligible))


def on_time_arrival(on_time_leg_count, recorded_completed_legs):
    if recorded_completed_legs == 0:
        return EMPTY_SET_RESULT_PCT
    return round2(Decimal(100) * Decimal(on_time_leg_count) /
                  Decimal(recorded_completed_legs))


def mishandled_bag_rate(mishandled_bags_total, enplaned_bags_total):
    if enplaned_bags_total == 0:
        return ZERO_BAGS_RESULT
    return round2(Decimal(1000) * Decimal(mishandled_bags_total) /
                  Decimal(enplaned_bags_total))


# --------------------------------------------- performance_incentive_penalty
def band_completion_factor(cf):
    if cf >= CF_TIER_HIGH_PCT:
        return 3
    if cf >= CF_TIER_MID_PCT:
        return 0
    return -4


def band_on_time(ota):
    if ota >= OTA_TIER_HIGH_PCT:
        return 2
    if ota >= OTA_TIER_MID_PCT:
        return 0
    return -3


def band_bags(bag):
    if bag <= BAG_TIER_LOW_PER_1000:
        return 1
    if bag <= BAG_TIER_MID_PER_1000:
        return 0
    return -2


def performance_incentive_penalty(cf, ota, bag, agreement, cycle):
    completion_factor_points = band_completion_factor(cf)
    on_time_raw = band_on_time(ota)
    bag_raw = band_bags(bag)

    if completion_factor_points < 0:
        on_time_points = min(0, on_time_raw)
        bag_points = min(0, bag_raw)
    else:
        on_time_points = on_time_raw
        bag_points = bag_raw

    points = completion_factor_points + on_time_points + bag_points
    gross = round2(Decimal(points) * POINT_VALUE_USD)

    if gross >= 0:
        _, fixed = fixed_component(agreement)
        variable = variable_flight_payment(cycle, agreement, "ACTUAL_BASIS")
        revenue_cap = round2(INCENTIVE_REVENUE_SHARE * (fixed + variable))
        incentive = min(gross, agreement["incentive_pool_cap_usd"], revenue_cap)
        penalty = ZERO2
    else:
        incentive = ZERO2
        penalty = min(-gross, agreement["penalty_cap_usd"])

    return {
        "completion_factor_points": completion_factor_points,
        "on_time_points": on_time_points,
        "bag_points": bag_points,
        "performance_points": points,
        "gross_performance_usd": gross,
        "incentive_usd": round2(incentive),
        "penalty_usd": round2(penalty),
    }


# ------------------------------------------------- brand_consistency_penalty
def exposed_brand_audits(agreement_id):
    base_ids = set(
        base["id"] for base in store.crew_bases.values()
        if base["agreement_id"] == agreement_id
    )
    audits = [
        audit for audit in store.brand_audits.values()
        if audit["base_id"] in base_ids
        and audit["finding_status"] in EXPOSED_FINDING_STATUSES
        and audit["remediation_status"] in EXPOSED_REMEDIATION_STATUSES
    ]
    return ordered(audits)


def brand_consistency_penalty(agreement_id):
    raw = ZERO2
    for audit in exposed_brand_audits(agreement_id):
        raw += Decimal(audit["findings_count"]) * SEVERITY_WEIGHT_USD[audit["severity"]]
    return min(round2(raw), BRAND_PENALTY_CAP_USD)


# ----------------------------------- passthrough_reconciliation_settlement
def passthrough_allowed_amount(claim):
    """Step 1: FUEL is uncapped, other categories are capped at the tolerance."""
    if claim["category"] == "FUEL":
        return round2(claim["actual_amount_usd"])
    tolerance = CATEGORY_TOLERANCE[claim["category"]]
    cap = round2(claim["estimated_amount_usd"] * (Decimal(1) + tolerance))
    return min(round2(claim["actual_amount_usd"]), cap)


def admin_fee_rate(base_total):
    if base_total <= ADMIN_TIER_1_USD:
        return ADMIN_FEE_TIER_LOW_RATE
    if base_total <= ADMIN_TIER_2_USD:
        return ADMIN_FEE_TIER_MID_RATE
    return ADMIN_FEE_TIER_HIGH_RATE


def passthrough_settlement(cycle_id):
    """Steps 2-5. The fee tier is chosen from the Step-2 base total only."""
    claims = ordered([
        claim for claim in store.passthrough_claims.values()
        if claim["cycle_id"] == cycle_id and claim["status"] == "RECONCILED"
    ])
    base_total = ZERO2
    for claim in claims:
        allowed = claim.get("allowed_amount_usd")
        if allowed is not None:
            base_total += allowed
    rate = admin_fee_rate(base_total)
    fee = round2(base_total * rate)
    return round2(base_total), fee, round2(base_total + fee)


def estimated_passthrough_total(cycle_id):
    total = ZERO2
    for claim in store.passthrough_claims.values():
        if claim["cycle_id"] != cycle_id:
            continue
        if claim["status"] in ("SUBMITTED", "ACTUAL_SUBMITTED", "RECONCILED"):
            total += claim["estimated_amount_usd"]
    return round2(total)


# -------------------------------------------------- pilot_staffing_shortfall
def base_pilot_counts(base_id):
    line_qualified = 0
    in_training = 0
    for pilot in store.pilots.values():
        if pilot["base_id"] != base_id:
            continue
        if pilot["status"] == "LINE_QUALIFIED":
            line_qualified += 1
        elif pilot["status"] == "IN_TRAINING":
            in_training += 1
    return line_qualified, in_training


def base_assigned_aircraft_count(base_id):
    return sum(
        1 for tail in store.aircraft.values()
        if tail["assigned_base_id"] == base_id
        and tail["status"] in FLEET_PAID_STATUSES
    )


def pilot_staffing_shortfall(base):
    """Both variants at once; HEADCOUNT_BASIS gates, PIPELINE_BASIS plans."""
    line_qualified, in_training = base_pilot_counts(base["id"])
    assigned = base_assigned_aircraft_count(base["id"])
    ratio = base["pilots_required_per_aircraft"]

    required = assigned * ratio

    headcount_available = line_qualified
    headcount_shortfall = max(0, required - headcount_available)

    pipeline_available = line_qualified + _floor(Decimal(in_training) * PIPELINE_CREDIT)
    pipeline_shortfall = max(0, required - pipeline_available)

    if headcount_shortfall == 0:
        posture = "STAFFED"
    elif headcount_shortfall <= ratio:
        posture = "SHORT"
    else:
        posture = "CRITICAL"

    allocatable = min(base["aircraft_allocation_cap"],
                      _floor(Decimal(pipeline_available) // Decimal(ratio)))

    return {
        "line_qualified_pilot_count": line_qualified,
        "in_training_pilot_count": in_training,
        "assigned_aircraft_count": assigned,
        "required_pilot_count": required,
        "headcount_shortfall": headcount_shortfall,
        "pipeline_shortfall": pipeline_shortfall,
        "staffing_posture": posture,
        "allocatable_aircraft_count": allocatable,
    }


# --------------------------------------------------------- invoice_settlement
def invoice_settlement(cycle, agreement, variant, scorecard):
    count, fixed = fixed_component(agreement)
    if variant == "PROVISIONAL":
        variable = variable_flight_payment(cycle, agreement, "PLANNED_BASIS")
        passthrough = cycle["estimated_passthrough_total_usd"]
        incentive = ZERO2
        penalty = ZERO2
        brand_penalty = ZERO2
    else:
        variable = variable_flight_payment(cycle, agreement, "ACTUAL_BASIS")
        passthrough = cycle["passthrough_settlement_usd"]
        incentive = scorecard["incentive_usd"] if scorecard else ZERO2
        penalty = scorecard["penalty_usd"] if scorecard else ZERO2
        brand_penalty = scorecard["brand_penalty_usd"] if scorecard else ZERO2

    total = fixed + variable + passthrough + incentive - penalty - brand_penalty
    return {
        "ownership_aircraft_count": count,
        "fixed_component_usd": round2(fixed),
        "variable_component_usd": round2(variable),
        "passthrough_component_usd": round2(passthrough),
        "incentive_component_usd": round2(incentive),
        "penalty_component_usd": round2(penalty),
        "brand_penalty_component_usd": round2(brand_penalty),
        "total_usd": round2(total),
    }

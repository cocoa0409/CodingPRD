"""Pure calculations (PRD sections 2.7, 3.1, 3.2, 3.5, 3.6, 3.7, 3.8, 3.9).

Every rounding is round-half-up on Decimal values; floats are never used for
arithmetic, only for JSON output of the already-rounded quantity.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# decimal helpers
# ---------------------------------------------------------------------------


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def rhu(value, places):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


def num(value, places):
    """Round half up to `places` and return a JSON-friendly float."""
    return float(rhu(value, places))


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

TIER1_UPPER_ERU = Decimal("1.00")
TIER2_UPPER_ERU = Decimal("4.00")
RATE_TIER1 = Decimal("9633")
RATE_TIER2 = Decimal("8207")
RATE_TIER3 = Decimal("6541")
SURCHARGE_PCT = {
    "RESIDENTIAL_SINGLE": Decimal("0.00"),
    "RESIDENTIAL_MULTI": Decimal("0.05"),
    "COMMERCIAL": Decimal("0.12"),
    "INSTITUTIONAL": Decimal("0.08"),
}
MAX_CREDIT_PCT = Decimal("0.5000")

BACTERIA_LIMIT = Decimal("1000")
SURFACTANT_LIMIT = Decimal("0.25")
AMMONIA_LIMIT = Decimal("0.50")
SUSPECT_INDICATOR_COUNT = 2
SURFACTANT_HARD_TRIGGER = Decimal("1.00")

WEIGHT_MINOR = 8
WEIGHT_MAJOR = 22
WEIGHT_CRITICAL = 34
RAINFALL_MULTIPLIER = Decimal("1.20")
LARGE_SITE_ACRES = Decimal("5.00")
LARGE_SITE_ADDER = 12
OVERDUE_ADDER = 15
NO_AGREEMENT_ADDER = 25
ESCALATION_THRESHOLD = 70

BASE_CENTS = {
    "NOTICE_OF_VIOLATION": 25000,
    "ADMINISTRATIVE_ORDER": 50000,
    "CIVIL_PENALTY": 100000,
}
PER_DAY_CENTS = 2000
MAX_BILLABLE_DAYS = 30
REPEAT_TIER_CENTS = 100000

MG_PER_L_KL_TO_LB = Decimal("0.00220462")
REQUIRED_SAMPLES_PER_YEAR = 4
LB_PER_LANE_MILE = Decimal("0.85")
CREDIT_CAP_PCT = Decimal("0.25")

MAX_OPEN_CASES = 3
MAX_SITE_ENFORCEMENTS = 2
MET_PCT = Decimal("100.00")
ON_TRACK_PCT = Decimal("75.00")
NON_COMPLIANT_BEHIND_COUNT = 2

SCREENING_BUFFER = timedelta(days=14)
COOLING_OFF = timedelta(days=14)
SUBMISSION_WINDOW_DAYS = 90


# ---------------------------------------------------------------------------
# utility fee (PRD 3.8)
# ---------------------------------------------------------------------------


def tiered_fee(impervious_area_sqft, eru_sqft, parcel_class):
    eru = rhu(D(impervious_area_sqft) / D(eru_sqft), 2)
    t1 = min(eru, TIER1_UPPER_ERU)
    t2 = min(max(eru - TIER1_UPPER_ERU, Decimal("0")), TIER2_UPPER_ERU - TIER1_UPPER_ERU)
    t3 = max(eru - TIER2_UPPER_ERU, Decimal("0"))
    c1 = cents(t1 * RATE_TIER1)
    c2 = cents(t2 * RATE_TIER2)
    c3 = cents(t3 * RATE_TIER3)
    gross_fee_cents = c1 + c2 + c3
    surcharge = cents(D(gross_fee_cents) * SURCHARGE_PCT[parcel_class])
    return {
        "eru_units": num(eru, 2),
        "gross_fee_cents": gross_fee_cents,
        "class_surcharge_cents": surcharge,
        "gross_billable_cents": gross_fee_cents + surcharge,
    }


def credit_pool(applications, variant):
    """Sum the contributions of an account's credit applications."""
    raw = Decimal("0")
    for app in applications:
        status = app.get("status")
        if status == "APPROVED":
            raw += D(app.get("approved_credit_pct") or 0)
        elif status == "SUBMITTED" and variant == "INTERIM":
            raw += D(app.get("requested_credit_pct") or 0)
    return min(MAX_CREDIT_PCT, rhu(raw, 4))


def apply_credit(gross_billable_cents, pct):
    credit = cents(D(gross_billable_cents) * D(pct))
    return credit, int(gross_billable_cents) - credit


# ---------------------------------------------------------------------------
# dry weather screening (PRD 3.2)
# ---------------------------------------------------------------------------


def screening_result(flow_present, bacteria, surfactant, ammonia):
    if not flow_present:
        return "CLEAR"
    exceed = 0
    if bacteria is not None and D(bacteria) > BACTERIA_LIMIT:
        exceed += 1
    if surfactant is not None and D(surfactant) > SURFACTANT_LIMIT:
        exceed += 1
    if ammonia is not None and D(ammonia) > AMMONIA_LIMIT:
        exceed += 1
    if exceed >= SUSPECT_INDICATOR_COUNT:
        return "SUSPECT"
    if surfactant is not None and D(surfactant) > SURFACTANT_HARD_TRIGGER:
        return "SUSPECT"
    return "CLEAR"


# ---------------------------------------------------------------------------
# deficiency score (PRD 3.5)
# ---------------------------------------------------------------------------


def deficiency_score(inspection, site=None, facility_state=None, facility=None):
    base = (
        WEIGHT_MINOR * int(inspection.get("minor_finding_count") or 0)
        + WEIGHT_MAJOR * int(inspection.get("major_finding_count") or 0)
        + WEIGHT_CRITICAL * int(inspection.get("critical_finding_count") or 0)
    )
    base = D(base)
    if inspection.get("inspection_type") == "CONSTRUCTION_ESC":
        if inspection.get("rainfall_trigger"):
            base = rhu(base * RAINFALL_MULTIPLIER, 0)
        if site is not None and D(site.get("disturbed_acres")) > LARGE_SITE_ACRES:
            base = base + LARGE_SITE_ADDER
    else:
        if facility_state and facility_state.get("inspection_overdue"):
            base = base + OVERDUE_ADDER
        if (
            facility is not None
            and facility.get("ownership") == "PRIVATE"
            and facility.get("agreement_status") != "RECORDED"
        ):
            base = base + NO_AGREEMENT_ADDER
    score = min(100, int(rhu(base, 0)))
    return score, score >= ESCALATION_THRESHOLD


# ---------------------------------------------------------------------------
# enforcement penalty (PRD 3.6)
# ---------------------------------------------------------------------------


def penalty(action_type, violation_days, prior_assessed_total_cents):
    billable_days = min(int(violation_days or 0), MAX_BILLABLE_DAYS)
    prior = int(prior_assessed_total_cents or 0)
    if prior == 0:
        multiplier = Decimal("1.00")
    elif prior < REPEAT_TIER_CENTS:
        multiplier = Decimal("1.50")
    else:
        multiplier = Decimal("2.25")
    amount = cents((D(BASE_CENTS[action_type]) + D(PER_DAY_CENTS) * billable_days) * multiplier)
    return billable_days, prior, multiplier, amount


# ---------------------------------------------------------------------------
# pollutant load (PRD 3.7)
# ---------------------------------------------------------------------------


def sample_load(concentration, volume):
    return num(D(concentration) * D(volume) * MG_PER_L_KL_TO_LB, 4)


def projected_unit_load(baseline_concentration, design_runoff_kl):
    return rhu(D(baseline_concentration) * D(design_runoff_kl) * MG_PER_L_KL_TO_LB, 4)


def sweeping_credit(lane_miles, gross_load_lb):
    earned = rhu(D(lane_miles) * LB_PER_LANE_MILE, 2)
    cap = rhu(D(gross_load_lb) * CREDIT_CAP_PCT, 2)
    return min(earned, cap)


def tmdl_status(term, net_load_lb):
    if not term.get("tmdl_applicable"):
        return "NOT_ASSESSED"
    if D(net_load_lb) > D(term.get("tmdl_wla_lb_per_year") or 0):
        return "EXCEEDING"
    return "ATTAINING"


# ---------------------------------------------------------------------------
# measurable goals and posture (PRD 3.1)
# ---------------------------------------------------------------------------


def attainment_pct(actual, target):
    if D(target) == 0:
        return Decimal("0.00")
    return rhu(Decimal("100") * D(actual) / D(target), 2)


def goal_status(measure, pct):
    code = measure.get("measure_code")
    if code == "ILLICIT_DISCHARGE" and int(measure.get("open_case_count") or 0) > MAX_OPEN_CASES:
        return "BEHIND"
    if (
        code == "CONSTRUCTION_RUNOFF"
        and int(measure.get("enforcement_count") or 0) >= MAX_SITE_ENFORCEMENTS
    ):
        return "BEHIND"
    if code == "MUNICIPAL_OPERATIONS" and (
        not measure.get("salt_storage_covered") or not measure.get("fleet_wash_recycle")
    ):
        return "BEHIND"
    if measure.get("last_progress_reported_at") is None and D(measure.get("measurable_goal_actual")) == 0:
        return "PENDING"
    if pct >= MET_PCT:
        return "MET"
    if pct >= ON_TRACK_PCT:
        return "ON_TRACK"
    return "BEHIND"


def posture(behind_measure_count, exceeding_outfall_count):
    if behind_measure_count >= NON_COMPLIANT_BEHIND_COUNT or (
        behind_measure_count >= 1 and exceeding_outfall_count >= 1
    ):
        return "NON_COMPLIANT"
    if behind_measure_count == 1 or exceeding_outfall_count >= 1:
        return "AT_RISK"
    return "COMPLIANT"


def compliance_index(measures):
    weighted = Decimal("0")
    total_weight = Decimal("0")
    for measure in measures:
        weight = D(measure.get("weight") or 0)
        pct = min(MET_PCT, D(measure.get("attainment_pct") or 0))
        weighted += weight * pct
        total_weight += weight
    if total_weight == 0:
        return Decimal("0.00")
    return rhu(weighted / total_weight, 2)


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------


def whole_months_between(start, end):
    """Whole months from `start` to `end`, fractional month discarded."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < (
        start.day,
        start.hour,
        start.minute,
        start.second,
        start.microsecond,
    ):
        months -= 1
    return max(0, months)


def window_bounds(period_start, period_end):
    start = datetime(
        period_start.year, period_start.month, period_start.day, 0, 0, 0, tzinfo=timezone.utc
    )
    end = datetime(
        period_end.year, period_end.month, period_end.day, 23, 59, 59, tzinfo=timezone.utc
    )
    return start, end


def in_window(instant, start, end):
    return instant is not None and start <= instant <= end

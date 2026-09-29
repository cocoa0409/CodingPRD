"""Calculation rules and their constants (PRD 2.6, 3.3, 3.6, 3.7, 3.8, 3.9)."""

from decimal import Decimal as D
from decimal import ROUND_HALF_UP

from timeutil import days_between, hours_between

# ------------------------------------------------------------------ rounding
ZERO = D("0")


def rnd(value, places):
    """Half-up rounding to a fixed number of decimal places (PRD 2.6)."""
    exp = D(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def r1(value):
    return rnd(value, 1)


def r2(value):
    return rnd(value, 2)


def rcents(value):
    """Half-up rounding to a whole number of cents (PRD 2.6)."""
    return int(D(value).quantize(D(1), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ constants
ROLE_NAMES = [
    "FieldOperationsCoordinator",
    "TurfAgronomist",
    "SafetyInspector",
    "CertificationOfficer",
    "FacilitiesDirector",
]

SURFACE_TYPES = ["NATURAL_GRASS", "SYNTHETIC_TURF"]
SANCTIONED_LEVELS = ["NONE", "LOCAL", "REGIONAL", "STATE"]
PLAY_STATUSES = ["OPEN", "RESTRICTED", "CLOSED_ADMIN", "CLOSED_UNSAFE", "RETIRED"]
CERTIFICATION_STATUSES = ["NOT_CERTIFIED", "PENDING_REVIEW", "CERTIFIED", "EXPIRED"]
TASK_TYPES = ["AERATION", "OVERSEEDING", "FERTILITY", "IRRIGATION",
              "GROOMING", "INFILL_REDISTRIBUTION", "SEAM_INSPECTION"]
NATURAL_TASK_TYPES = {"AERATION", "OVERSEEDING", "FERTILITY", "IRRIGATION"}
SYNTHETIC_TASK_TYPES = {"GROOMING", "INFILL_REDISTRIBUTION", "SEAM_INSPECTION"}
TASK_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
ASSESSMENT_TYPES = ["IMPACT_ATTENUATION", "GOAL_ANCHORING", "STRIPING_LAYOUT"]
ASSESSMENT_STATUSES = ["RECORDED", "SUPERSEDED", "VOIDED"]
ASSESSMENT_RESULTS = ["PASS", "ADVISORY", "FAIL"]
DECLARED_RESULTS = ["PASS", "FAIL"]
ORDER_SEVERITIES = ["MANDATORY", "ADVISORY"]
ORDER_STATUSES = ["OPEN", "VERIFICATION_SUBMITTED", "CLOSED_VERIFIED", "CANCELLED"]
ACTIVITY_TYPES = ["PRACTICE", "GAME", "TOURNAMENT", "COMMUNITY"]
BOOKING_STATUSES = ["SCHEDULED", "CONFIRMED", "PLAYED", "RAINED_OUT",
                    "CANCELLED_LATE", "CANCELLED_UNSAFE"]
CLOSE_OUT_OUTCOMES = ["PLAYED", "RAINED_OUT", "CANCELLED_LATE"]
WEATHER_CONDITIONS = ["DRY", "WET"]
ENTRY_TYPES = ["PLAY_WEAR", "RAIN_OUT_RELIEF", "LATE_CANCEL_WEAR",
               "UNSAFE_CANCELLATION", "RECOVERY_CREDIT"]
PACKET_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "SUPERSEDED"]
FUNDING_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "RESCINDED", "DEFERRED"]
DISPOSAL_STATUSES = ["NOT_APPLICABLE", "PENDING", "MANIFESTED", "COMPLETED"]
PRIORITY_BASES = ["REMAINING_LIFE", "CONDITION_RISK"]
BUDGET_STATUSES = ["OPEN", "LOCKED"]

# field_age_and_warranty_status
DAYS_PER_YEAR = D("365.25")

# impact_attenuation_result
GMAX_ADVISORY_LIMIT = D("165.0")
GMAX_MANDATORY_LIMIT = D("200.0")

# wear_load_units
ACTIVITY_INTENSITY = {"PRACTICE": D("1.00"), "GAME": D("1.50"),
                     "TOURNAMENT": D("2.00"), "COMMUNITY": D("0.75")}
CROWD_FREE_ALLOWANCE = 40
CROWD_STEP = D("0.01")
CROWD_FACTOR_CAP = D("0.50")
SURFACE_FACTOR = {"NATURAL_GRASS": D("1.20"), "SYNTHETIC_TURF": D("0.80")}
WET_FACTOR = D("1.35")
LATE_CANCEL_WEAR_FRACTION = D("0.50")

# rest_requirement_hours
REST_TIERS = [(D("6.00"), D("0.50")), (D("12.00"), D("1.00")), (None, D("1.75"))]
SYNTHETIC_REST_MULTIPLIER = D("0.40")
WET_NATURAL_REST_SURCHARGE_HOURS = D("2.00")

# field_rest_debt_hours
RECOVERY_CREDIT_HOURS = {
    "AERATION": D("12.00"),
    "OVERSEEDING": D("24.00"),
    "FERTILITY": D("6.00"),
    "IRRIGATION": D("4.00"),
    "GROOMING": D("3.00"),
    "INFILL_REDISTRIBUTION": D("6.00"),
    "SEAM_INSPECTION": D("0.00"),
}

# field_condition_index
WEAR_UNITS_PER_INDEX_POINT = D("4.00")
GMAX_IDEAL_VALUE = D("90.0")
NO_DATA_SAFETY_COMPONENT = D("50.00")

# certification_document_completeness_score
CERTIFICATION_WINDOW_DAYS = 180
COMPONENT_WEIGHTS = {
    "SAFETY_TEST": D("30"),
    "AGRONOMIC_PROGRAM": D("20"),
    "STRIPING_LAYOUT": D("15"),
    "GOAL_ANCHORING": D("15"),
    "SURFACE_SPEC_COMPLIANCE": D("10"),
    "REMEDIATION_CLOSURE": D("10"),
}
REQUIRED_INFILL_DEPTH_MM = D("51.0")
REQUIRED_NITROGEN_LB_PER_1000_SQ_FT = D("3.00")
MIN_CERTIFICATION_COMPLETENESS_SCORE = D("90.00")
MIN_CERTIFICATION_CONDITION_INDEX = D("55.00")
CERTIFICATION_VALID_DAYS = 365

# plan_funding_amount_cents
COST_PER_SQ_FT_CENTS = {"NATURAL_GRASS": 22, "SYNTHETIC_TURF": 65}
SYNTHETIC_DISPOSAL_CENTS_PER_SQ_FT = 5

# replacement_priority_score
AGE_POINTS_PER_YEAR = D("6.00")
WEAR_UNITS_PER_PRIORITY_POINT = D("25.00")
WEAR_POINTS_CAP = D("20.00")
CONDITION_POINTS_PER_INDEX_POINT = D("0.80")
MANDATORY_ORDER_POINTS = D("5.00")
WARRANTY_EXPIRED_PENALTY = D("8.00")
PRIORITY_LOOKBACK_DAYS = 365
MIN_APPROVAL_PRIORITY_SCORE = D("20.00")

# capital_budget_commitment
BUDGET_LOCK_TRIGGER_RATIO = D("0.90")

# disposal
MIN_DIVERSION_RATIO = D("0.75")

# interval semantics
CHANGEOVER_BUFFER_MINUTES = 30
MAX_CONCURRENT_STAFF_TASKS = 2

ALLOWED_ACTIVITIES = {
    "OPEN": {"PRACTICE", "GAME", "TOURNAMENT", "COMMUNITY"},
    "RESTRICTED": {"PRACTICE", "COMMUNITY"},
    "CLOSED_ADMIN": set(),
    "CLOSED_UNSAFE": set(),
    "RETIRED": set(),
}


# ------------------------------------------------- field_age_and_warranty_status
def field_age_years(installed_on_date, current):
    elapsed_days = days_between(installed_on_date.dt, current.dt)
    return r2(elapsed_days / DAYS_PER_YEAR)


def field_warranty_status(warranty_expires_on, current):
    if warranty_expires_on is None:
        return "NONE"
    if current.dt < warranty_expires_on.dt:
        return "ACTIVE"
    return "EXPIRED"


# ------------------------------------------------- impact_attenuation_result
def impact_attenuation_result(readings):
    mean = r1((readings[0] + readings[1] + readings[2]) / D(3))
    if mean <= GMAX_ADVISORY_LIMIT:
        result = "PASS"
    elif mean <= GMAX_MANDATORY_LIMIT:
        result = "ADVISORY"
    else:
        result = "FAIL"
    return mean, result


# ------------------------------------------------- wear_load_units
def wear_load_units(outcome, activity_type, surface_type, weather_condition,
                    window_start, window_end, actual_duration_hours,
                    actual_participant_count, expected_participant_count):
    if outcome == "CANCELLED_LATE":
        duration = hours_between(window_start.dt, window_end.dt)
        headcount = D(expected_participant_count)
    else:
        duration = D(actual_duration_hours)
        headcount = D(actual_participant_count)

    base_units = duration * ACTIVITY_INTENSITY[activity_type]
    surcharge = max(ZERO, headcount - D(CROWD_FREE_ALLOWANCE)) * CROWD_STEP
    crowd_factor = D("1.00") + min(CROWD_FACTOR_CAP, surcharge)
    surface_factor = SURFACE_FACTOR[surface_type]
    weather_factor = WET_FACTOR if weather_condition == "WET" else D("1.00")

    raw = base_units * crowd_factor * surface_factor * weather_factor
    if outcome == "CANCELLED_LATE":
        return r2(LATE_CANCEL_WEAR_FRACTION * raw)
    return r2(raw)


# ------------------------------------------------- rest_requirement_hours
def rest_requirement_hours(wear_units, surface_type, weather_condition):
    remaining = D(wear_units)
    hours = ZERO
    lower = ZERO
    for upper, rate in REST_TIERS:
        if upper is None:
            span = max(ZERO, remaining - lower)
        else:
            span = max(ZERO, min(remaining, upper) - lower)
        hours = hours + span * rate
        if upper is not None:
            lower = upper

    if surface_type == "SYNTHETIC_TURF":
        hours = hours * SYNTHETIC_REST_MULTIPLIER
    elif weather_condition == "WET":
        hours = hours + WET_NATURAL_REST_SURCHARGE_HOURS
    return r2(hours)


# ------------------------------------------------- field_condition_index
def condition_components(cumulative_wear_units, age_years, expected_life_years,
                         latest_gmax_mean_value):
    wear_component = r2(max(ZERO, D("100.00")
                            - D(cumulative_wear_units) / WEAR_UNITS_PER_INDEX_POINT))
    age_component = r2(max(ZERO, D("100.00")
                           - (D(age_years) / D(expected_life_years)) * D("100.00")))
    if latest_gmax_mean_value is None:
        safety_component = NO_DATA_SAFETY_COMPONENT
    else:
        ratio = ((GMAX_MANDATORY_LIMIT - D(latest_gmax_mean_value))
                 / (GMAX_MANDATORY_LIMIT - GMAX_IDEAL_VALUE)) * D("100.00")
        safety_component = r2(min(D("100.00"), max(ZERO, ratio)))
    return wear_component, age_component, safety_component


def condition_index(cumulative_wear_units, age_years, expected_life_years,
                    latest_gmax_mean_value, variant):
    wear, age, safety = condition_components(
        cumulative_wear_units, age_years, expected_life_years, latest_gmax_mean_value)
    if variant == "AGRONOMIC":
        return r2(wear * D("0.50") + age * D("0.20") + safety * D("0.30"))
    value = r2(wear * D("0.20") + age * D("0.20") + safety * D("0.60"))
    return min(value, safety)


# ------------------------------------------------- plan_funding_amount_cents
def contingency_rate_for(pre_contingency_subtotal_cents):
    if pre_contingency_subtotal_cents < 2000000:
        return D("0.10")
    if pre_contingency_subtotal_cents < 5000000:
        return D("0.07")
    return D("0.05")


def plan_pricing(area_sq_ft, target_surface_type, existing_surface_type):
    base_construction_cents = area_sq_ft * COST_PER_SQ_FT_CENTS[target_surface_type]
    if existing_surface_type == "SYNTHETIC_TURF":
        disposal_cents = area_sq_ft * SYNTHETIC_DISPOSAL_CENTS_PER_SQ_FT
    else:
        disposal_cents = 0
    subtotal = base_construction_cents + disposal_cents
    rate = contingency_rate_for(subtotal)
    contingency_cents = rcents(D(subtotal) * rate)
    return {
        "base_construction_cents": base_construction_cents,
        "disposal_cents": disposal_cents,
        "pre_contingency_subtotal_cents": subtotal,
        "contingency_rate": rate,
        "contingency_cents": contingency_cents,
        "plan_funding_amount_cents": subtotal + contingency_cents,
    }


# ------------------------------------------------- replacement_priority_score
def replacement_priority_score(basis, field, mandatory_order_count):
    penalty = (WARRANTY_EXPIRED_PENALTY
               if field["warranty_status"] == "EXPIRED" else D("0.00"))
    if basis == "REMAINING_LIFE":
        deficit = max(ZERO, r2(D(field["age_years"]) - D(field["expected_life_years"])))
        wear_points = min(WEAR_POINTS_CAP,
                          D(field["cumulative_wear_units"]) / WEAR_UNITS_PER_PRIORITY_POINT)
        return r2(deficit * AGE_POINTS_PER_YEAR + wear_points + penalty)
    shortfall = (D("100.00") - D(field["condition_index_agronomic"]))
    return r2(shortfall * CONDITION_POINTS_PER_INDEX_POINT
              + D(mandatory_order_count) * MANDATORY_ORDER_POINTS
              + penalty)

"""Pure calculation functions (PRD §3, scaffold §1.3).

All integer arithmetic. No floats for money/scores. Rounding rules are pinned
exactly as the PRD prose dictates.
"""
import math

# ---- constants ----
CAT2_SEATS = 50
CAT3_SEATS = 150
INTERVAL = {"CATEGORY_1": 365, "CATEGORY_2": 180, "CATEGORY_3": 90}

BASE_SCORE = 100
A_CUT = 90
B_CUT = 80
CRITICAL_CLOSE_COUNT = 3
HARD_CLOSE_SCORE = 60

PLAN_BASE_FEE_CENTS = 20000
PLAN_EQUIP_FEE_CENTS = 1500
PLAN_T2_RATE = 50
PLAN_T3_RATE = 80

PERMIT_FEE = {"CATEGORY_1": 30000, "CATEGORY_2": 60000, "CATEGORY_3": 120000}

ILL_CAP = 10
ILL_POINT = 4
URGENT_CUT = 60
PRIORITY_CUT = 30
COMPLAINT_TYPE_WEIGHT = {"FOODBORNE_ILLNESS": 40, "SANITATION": 15, "OTHER": 5}
COMPLAINT_RISK_WEIGHT = {"CATEGORY_1": 0, "CATEGORY_2": 5, "CATEGORY_3": 10}

REDUCED_RATIO_NUM = 1  # halve via floor(x/2) to keep integer cents
REDUCED_RATIO_DEN = 2

PERMIT_TERM_DAYS = 365
REINSPECTION_GRACE_DAYS = 14

_CATEGORY_ORDER = ["CATEGORY_1", "CATEGORY_2", "CATEGORY_3"]
_GRADE_SEVERITY = {"A": 0, "B": 1, "C": 2, "CLOSED": 3}
_SEVERITY_GRADE = {0: "A", 1: "B", 2: "C", 3: "CLOSED"}


def _bump_one(category):
    idx = _CATEGORY_ORDER.index(category)
    return _CATEGORY_ORDER[min(idx + 1, len(_CATEGORY_ORDER) - 1)]


def risk_category_assignment(seating_capacity, serves_raw_animal_foods, does_onsite_processing):
    """Returns (risk_category, routine_interval_days). Order is pinned:
    seating band first, then escalators in declared order, ceiling at CATEGORY_3.
    """
    base = "CATEGORY_1"
    if seating_capacity >= CAT2_SEATS:
        base = "CATEGORY_2"
    if seating_capacity >= CAT3_SEATS:
        base = "CATEGORY_3"
    if serves_raw_animal_foods:
        base = _bump_one(base)
    if does_onsite_processing:
        base = _bump_one(base)
    return base, INTERVAL[base]


def plan_review_fee(submitted_layout_sqft, equipment_count):
    """Marginal sqft tiering + per-equipment flat fee. Integer cents."""
    fee = PLAN_BASE_FEE_CENTS
    remaining = submitted_layout_sqft
    tier1 = min(remaining, 500)        # 0..500 sqft @ 0
    remaining -= tier1
    tier2 = min(remaining, 1000)       # 501..1500 sqft @ 50
    remaining -= tier2
    fee += tier2 * PLAN_T2_RATE
    tier3 = remaining                  # 1501+ sqft @ 80
    fee += tier3 * PLAN_T3_RATE
    fee += equipment_count * PLAN_EQUIP_FEE_CENTS
    return fee


def permit_fee(risk_category):
    return PERMIT_FEE[risk_category]


def violation_points(base_demerit_points, repeat_surcharge_points, repeat_offense, corrected_on_site):
    """Per-violation observed and final point contributions.

    observed = base + (surcharge if repeat else 0)
    final    = ceil(observed / 2) if corrected_on_site else observed
    Rounding (halve-then-ceil) is applied per violation BEFORE summation.
    """
    observed = base_demerit_points + (repeat_surcharge_points if repeat_offense else 0)
    if corrected_on_site:
        final = math.ceil(observed / 2)
    else:
        final = observed
    return observed, final


def inspection_scores(violations):
    """violations: list of dicts each carrying demerit_points_observed,
    demerit_points_final, classification.

    Sum-then-clamp model: aggregate raw points across all violations first,
    subtract from 100, then clamp to [0, 100] once.
    """
    observed_total = sum(v["demerit_points_observed"] for v in violations)
    final_total = sum(v["demerit_points_final"] for v in violations)
    as_observed = max(0, min(100, BASE_SCORE - observed_total))
    final_score = max(0, min(100, BASE_SCORE - final_total))
    critical_count = sum(1 for v in violations if v["classification"] == "CRITICAL")
    return as_observed, final_score, critical_count


def grade_assignment(final_score, critical_count):
    """Returns (grade, placard_color). Pinned order: score_band, cap_band,
    worst-of, THEN CLOSED override.
    """
    if final_score >= A_CUT:
        score_band = "A"
    elif final_score >= B_CUT:
        score_band = "B"
    else:
        score_band = "C"

    if critical_count == 0:
        cap_band = "A"
    elif critical_count == 1:
        cap_band = "B"
    else:
        cap_band = "C"

    worst = _SEVERITY_GRADE[max(_GRADE_SEVERITY[score_band], _GRADE_SEVERITY[cap_band])]
    grade = worst
    if critical_count >= CRITICAL_CLOSE_COUNT or final_score < HARD_CLOSE_SCORE:
        grade = "CLOSED"

    placard = {"A": "GREEN", "B": "YELLOW", "C": "YELLOW", "CLOSED": "RED"}[grade]
    return grade, placard


def closure_trigger(critical_count, final_score):
    """Reason code when grade == CLOSED. Critical-count cause takes precedence."""
    if critical_count >= CRITICAL_CLOSE_COUNT:
        return "CRITICAL_THRESHOLD"
    elif final_score < HARD_CLOSE_SCORE:
        return "GRADE_C_AUTOCLOSE"
    else:
        return "IMMINENT_HEALTH_HAZARD"


def complaint_severity(complaint_type, reported_ill_count, risk_category):
    """Returns (severity_score, priority)."""
    type_weight = COMPLAINT_TYPE_WEIGHT[complaint_type]
    ill_weight = min(reported_ill_count, ILL_CAP) * ILL_POINT
    risk_weight = COMPLAINT_RISK_WEIGHT[risk_category]
    severity = type_weight + ill_weight + risk_weight
    if severity >= URGENT_CUT:
        priority = "URGENT"
    elif severity >= PRIORITY_CUT:
        priority = "PRIORITY"
    else:
        priority = "ROUTINE"
    return severity, priority


def penalty_assessment(ruling, alleged_penalty_cents):
    """Ruling -> assessed cents. floor on reduction."""
    if ruling == "DISMISSED":
        return 0
    elif ruling == "REDUCED":
        return (alleged_penalty_cents * REDUCED_RATIO_NUM) // REDUCED_RATIO_DEN
    elif ruling == "UPHELD":
        return alleged_penalty_cents
    return alleged_penalty_cents

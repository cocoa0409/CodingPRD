"""The seven calculation rules of SCAFFOLD §1.3.

Every evaluation order pinned by the scaffold is reproduced literally:
  * consult_acuity_score      round to 1dp FIRST, then clamp to ACUITY_MAX
  * rental_cost_projection    round_half_up ONCE PER DAY, then sum
  * vendor_service_fee        fee tier keyed on the PRE-fee projected figure
  * certification_eligibility components are never individually rounded
"""

import math
from decimal import Decimal

from core import (
    BILLABLE_DAY_HOURS,
    D,
    HOURS_PER_WEEK,
    POA_WINDOW_HOURS,
    SLA_HOURS_BY_BAND,
    add_hours,
    dt_of,
    round_half_up,
    whole_hours_between,
)

# ---------------------------------------------------------------------------
# 1. consult_acuity_score
# ---------------------------------------------------------------------------
STAGE_WEIGHT = {
    "NONE": 0,
    "MUCOSAL": 15,
    "STAGE_1": 20,
    "STAGE_2": 35,
    "DTI": 45,
    "STAGE_3": 60,
    "UNSTAGEABLE": 70,
    "STAGE_4": 80,
}
TYPE_MULTIPLIER = {
    "WOUND": Decimal("1.00"),
    "OSTOMY": Decimal("1.15"),
    "INCONTINENCE": Decimal("0.90"),
}
COMORBIDITY_POINTS_EACH = 5
COMORBIDITY_POINTS_CAP = 25
DEVICE_RELATED_POINTS = 10
AREA_POINTS_STEP_CM2 = 10
AREA_POINTS_PER_STEP = 5
AREA_POINTS_CAP = 15
ACUITY_MAX = Decimal("100")
P1_THRESHOLD = Decimal("70.0")
P2_THRESHOLD = Decimal("40.0")

VARIANT_INTAKE = "INTAKE_PROVISIONAL"
VARIANT_ASSESSED = "ASSESSED_FINAL"


def acuity_score(stage_source, comorbidity_count, device_related_risk,
                 consult_type, measured_area_cm2=None):
    base_points = D(STAGE_WEIGHT.get(stage_source or "NONE", 0))
    comorbid_points = D(min(COMORBIDITY_POINTS_CAP,
                            COMORBIDITY_POINTS_EACH * int(comorbidity_count or 0)))
    device_points = D(DEVICE_RELATED_POINTS) if device_related_risk else D(0)
    if measured_area_cm2 is None:
        area_points = D(0)
    else:
        steps = int(D(measured_area_cm2) // D(AREA_POINTS_STEP_CM2))
        area_points = D(min(AREA_POINTS_CAP, steps * AREA_POINTS_PER_STEP))
    raw = (base_points + comorbid_points + device_points + area_points) \
        * TYPE_MULTIPLIER[consult_type]
    # PINNED: round to one decimal first, clamp afterwards.
    rounded = round_half_up(raw, 1)
    return min(ACUITY_MAX, rounded)


def priority_band(score):
    value = D(score)
    if value >= P1_THRESHOLD:
        return "P1"
    if value >= P2_THRESHOLD:
        return "P2"
    return "P3"


def sla_due_at(triaged_at, band):
    if triaged_at is None or band is None:
        return None
    return add_hours(triaged_at, SLA_HOURS_BY_BAND[band])


# ---------------------------------------------------------------------------
# 2. unit_survey_metric
# ---------------------------------------------------------------------------
PERCENT_SCALE = 100
EMPTY_DENOMINATOR_RESULT = Decimal("0.00")


def _rate(numerator, denominator):
    if denominator == 0:
        return EMPTY_DENOMINATOR_RESULT
    return round_half_up(D(PERCENT_SCALE) * D(numerator) / D(denominator), 2)


def prevalence_metric(observations):
    numerator = sum(1 for o in observations if o.get("injury_present") is True)
    denominator = len(observations)
    return numerator, denominator, _rate(numerator, denominator)


def incidence_metric(observations, window_start, window_end):
    numerator = 0
    for o in observations:
        if o.get("injury_present") is not True:
            continue
        if o.get("classification") != "HAPI":
            continue
        onset = o.get("onset_at")
        if onset is None:
            continue
        # CLOSED interval on both ends.
        if window_start <= onset <= window_end:
            numerator += 1
    denominator = sum(1 for o in observations if o.get("at_risk") is True)
    return numerator, denominator, _rate(numerator, denominator)


# ---------------------------------------------------------------------------
# 3. rental_cost_projection
# ---------------------------------------------------------------------------
TIER_1_LAST_DAY = 7
TIER_2_LAST_DAY = 21
TIER_1_FACTOR = Decimal("1.00")
TIER_2_FACTOR = Decimal("0.90")
TIER_3_FACTOR = Decimal("0.75")


def billable_days(interval_start, interval_end):
    hours = whole_hours_between(interval_start, interval_end)
    if hours <= 0:
        return 1
    return int(math.ceil(hours / float(BILLABLE_DAY_HOURS))) or 1


def _day_factor(day_index):
    if day_index <= TIER_1_LAST_DAY:
        return TIER_1_FACTOR
    if day_index <= TIER_2_LAST_DAY:
        return TIER_2_FACTOR
    return TIER_3_FACTOR


def rental_cost_projection(daily_rate_cents, days):
    """PINNED: round each day's charge, then sum the rounded figures."""
    total = 0
    rate = D(daily_rate_cents)
    for day in range(1, int(days) + 1):
        total += int(round_half_up(rate * _day_factor(day), 0))
    return total


# ---------------------------------------------------------------------------
# 4. vendor_service_fee
# ---------------------------------------------------------------------------
FEE_TIER_2_FLOOR = 50000
FEE_TIER_3_FLOOR = 200000
FEE_PCT_TIER_1 = Decimal("0.08")
FEE_PCT_TIER_2 = Decimal("0.05")
FEE_PCT_TIER_3 = Decimal("0.03")


def vendor_service_fee(projected_cost_cents):
    """PINNED: the tier is keyed on the PRE-fee projected figure."""
    projected = int(projected_cost_cents)
    if projected < FEE_TIER_2_FLOOR:
        pct = FEE_PCT_TIER_1
    elif projected < FEE_TIER_3_FLOOR:
        pct = FEE_PCT_TIER_2
    else:
        pct = FEE_PCT_TIER_3
    fee = int(round_half_up(D(projected) * pct, 0))
    return fee, projected + fee


def price_rental(daily_rate_cents, interval_start, interval_end):
    """Returns (billable_days, projected, fee, authorized)."""
    days = billable_days(interval_start, interval_end)
    projected = rental_cost_projection(daily_rate_cents, days)
    fee, authorized = vendor_service_fee(projected)
    return days, projected, fee, authorized


# ---------------------------------------------------------------------------
# 5. poa_determination
# ---------------------------------------------------------------------------
POA_CANDIDATE_STATUSES = (
    "PENDING_VALIDATION",
    "VALIDATED",
    "DISPUTED",
    "SUPERSEDED",
)


def poa_candidates(assessments, patient_id, anatomic_location):
    rows = [
        a for a in assessments
        if a.get("patient_id") == patient_id
        and a.get("anatomic_location") == anatomic_location
        and a.get("validation_status") in POA_CANDIDATE_STATUSES
    ]
    # observed_at ASC, created_at ASC as the sole tie-break; id is never used.
    return sorted(rows, key=lambda a: (a.get("observed_at") or "",
                                       a.get("created_at") or "",
                                       a.get("_seq", 0)))


def poa_determination(assessments, assessment, patient, confirmed):
    window_end = add_hours(patient.get("admitted_at"), POA_WINDOW_HOURS)
    ordered = poa_candidates(assessments, assessment.get("patient_id"),
                             assessment.get("anatomic_location"))
    earliest = ordered[0].get("observed_at") if ordered else assessment.get("observed_at")
    if confirmed is True:
        return "POA"
    if confirmed is False and earliest is not None and window_end is not None \
            and earliest > window_end:
        # Strictly greater: observed_at == window_end is still inside the window.
        return "HAPI"
    return "INDETERMINATE"


def poa_window_open(patient, clock_now):
    """The POA window is closed once the logical clock passes
    admitted_at + POA_WINDOW_HOURS."""
    window_end = add_hours(patient.get("admitted_at"), POA_WINDOW_HOURS)
    if window_end is None:
        return True
    return dt_of(clock_now) <= dt_of(window_end)


# ---------------------------------------------------------------------------
# 6. certification_eligibility_score
# ---------------------------------------------------------------------------
MONTH_HOURS = 720
RECENCY_BASE = 100
RECENCY_DECAY_PER_MONTH = 5
CREDIT_POINTS_PER_UNIT = 2
CREDIT_COMPONENT_CAP = 60
MENTORED_POINTS_PER_CONSULT = 10
MENTORED_CONSULT_CAP = 4
WEIGHT_RECENCY = Decimal("0.4")
WEIGHT_CREDITS = Decimal("0.4")
WEIGHT_MENTORED = Decimal("0.2")


def certification_eligibility_score(nurse, clock_now):
    last = nurse.get("last_competency_signoff_at")
    if last is None:
        months_since = 0
    else:
        hours = whole_hours_between(last, clock_now)
        months_since = int(hours // MONTH_HOURS)
        if months_since < 0:
            months_since = 0
    recency = D(max(0, RECENCY_BASE - RECENCY_DECAY_PER_MONTH * months_since))
    credits = D(min(CREDIT_COMPONENT_CAP,
                    CREDIT_POINTS_PER_UNIT * int(nurse.get("ce_credits") or 0)))
    mentored = D(MENTORED_POINTS_PER_CONSULT
                 * min(MENTORED_CONSULT_CAP,
                       int(nurse.get("mentored_consult_count") or 0)))
    # The three components are never individually rounded.
    return round_half_up(WEIGHT_RECENCY * recency
                         + WEIGHT_CREDITS * credits
                         + WEIGHT_MENTORED * mentored, 2)


# ---------------------------------------------------------------------------
# 7. dressing_protocol_weekly_cost
# ---------------------------------------------------------------------------
NON_FORMULARY_SURCHARGE_PCT = Decimal("0.20")


def changes_per_week(change_frequency_hours):
    return int(HOURS_PER_WEEK // int(change_frequency_hours))


def dressing_protocol_weekly_cost(change_frequency_hours, unit_cost_cents,
                                  units_per_change, formulary_tier):
    changes = changes_per_week(change_frequency_hours)
    base = changes * int(unit_cost_cents) * int(units_per_change)
    if formulary_tier in ("PREFERRED", "RESTRICTED"):
        return changes, base
    surcharged = int(round_half_up(D(base) * (Decimal("1") + NON_FORMULARY_SURCHARGE_PCT), 0))
    return changes, surcharged

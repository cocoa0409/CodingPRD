"""The fifteen calculations of PRD section 3, each one a pure function of the
rows it is handed plus the logical clock. Nothing here writes state except the
lazy coverage-window expiry, which the spec explicitly makes a read-time flip.
"""
from datetime import timedelta

from store import store, touch, ordered
from util import (LEVEL_ORDINAL, OUTCOME_ORDINAL, add_hours, ceil_div,
                  ceil_to_multiple, full_years_between, hhmm_to_minutes,
                  next_day_at, overlap_minutes, round_half_up_1dp,
                  round_half_up_cents)

WEEKEND_ISO_WEEKDAYS = (6, 7)

RED_FLAG_WEIGHT = 8
RED_FLAG_CAP = 24
GERIATRIC_AGE_YEARS = 65
GERIATRIC_POINTS = 12
PEDIATRIC_AGE_YEARS = 12
PEDIATRIC_POINTS = 10
PREGNANT_POINTS = 15
POSTPARTUM_POINTS = 8

BAND_EMERGENCY_911_MIN = 85
BAND_ED_NOW_MIN = 70
BAND_URGENT_CARE_24H_MIN = 50
BAND_OFFICE_APPT_72H_MIN = 30

BILLING_INCREMENT_MINUTES = 5
ESCALATION_UNIT_CENTS = 2500

HIGH_RISK_MIN_LEVEL_ORDINAL = 4
HIGH_RISK_DUE_HOURS = 2
STANDARD_DUE_HOURS = 12
HIGH_RISK_MAX_ATTEMPTS = 3
STANDARD_MAX_ATTEMPTS = 2

AVG_HANDLE_MINUTES = 14
TARGET_OCCUPANCY_PCT = 80

BLOCKED_REASON = "PRACTICE_UNDER_COMPLIANCE_REVIEW"


# ---------------------------------------------------------------------------
# 1. after_hours_determination — frozen on the call at intake
# ---------------------------------------------------------------------------
def after_hours_determination(practice, moment=None):
    clock = moment if moment is not None else store.clock
    minute_of_day = clock.hour * 60 + clock.minute
    open_minute = hhmm_to_minutes(practice["office_open_utc_hhmm"])
    close_minute = hhmm_to_minutes(practice["office_close_utc_hhmm"])
    is_weekend = clock.isoweekday() in WEEKEND_ISO_WEEKDAYS
    if practice["weekend_is_after_hours"] and is_weekend:
        return True
    return not (open_minute <= minute_of_day < close_minute)


# ---------------------------------------------------------------------------
# 2. intake_coverage_check, with the lazy ACTIVE -> EXPIRED flip
# ---------------------------------------------------------------------------
def lazy_expire_coverage_windows(practice_id=None):
    """Flip every ACTIVE window the clock has run past to EXPIRED, bumping its
    version. Runs before every individual read, every practice listing and every
    intake coverage check."""
    for window in ordered(store.coverage_windows):
        if practice_id is not None and window["practice_id"] != practice_id:
            continue
        if window["status"] == "ACTIVE" and store.clock >= window["end_utc"]:
            window["status"] = "EXPIRED"
            touch(window)


def has_active_coverage(practice_id):
    lazy_expire_coverage_windows(practice_id)
    for window in store.coverage_windows.values():
        if window["practice_id"] != practice_id:
            continue
        if window["status"] != "ACTIVE":
            continue
        if window["start_utc"] <= store.clock < window["end_utc"]:
            return True
    return False


# ---------------------------------------------------------------------------
# 3 & 4. licence and shift status, derived from the clock and never stored
# ---------------------------------------------------------------------------
def license_status(lic):
    return "ACTIVE" if lic["expires_on"] >= store.clock.date() else "EXPIRED"


def shift_status(shift):
    if store.clock < shift["start_utc"]:
        return "SCHEDULED"
    if store.clock < shift["end_utc"]:
        return "ACTIVE"
    return "ENDED"


def nurse_has_active_license(nurse_id, state_code):
    for lic in store.licenses.values():
        if lic["nurse_id"] != nurse_id or lic["state_code"] != state_code:
            continue
        if license_status(lic) == "ACTIVE":
            return True
    return False


def nurse_on_running_shift(nurse_id):
    for shift in store.shifts.values():
        if shift["nurse_id"] != nurse_id:
            continue
        if shift["start_utc"] <= store.clock < shift["end_utc"]:
            return True
    return False


# ---------------------------------------------------------------------------
# 5. assessment_acuity_score — two variants over one shared core
# ---------------------------------------------------------------------------
def age_modifier_points(age_years_used, protocol):
    if age_years_used < 1:
        return protocol["infant_modifier_points"]
    if age_years_used < PEDIATRIC_AGE_YEARS:
        return PEDIATRIC_POINTS
    if age_years_used >= GERIATRIC_AGE_YEARS:
        return GERIATRIC_POINTS
    return 0


def pregnancy_modifier_points(status_used, protocol):
    if not protocol["pregnancy_sensitive"]:
        return 0
    if status_used == "PREGNANT":
        return PREGNANT_POINTS
    if status_used == "POSTPARTUM_6W":
        return POSTPARTUM_POINTS
    return 0


def red_flag_points(red_flag_count):
    return min(RED_FLAG_CAP, red_flag_count * RED_FLAG_WEIGHT)


def variant_inputs(mode, stated_age_years, confirmed_pregnancy_status, patient):
    """PROVISIONAL reads the caller's words and the chart's pregnancy status;
    CONFIRMED recomputes the age from the chart's dob and takes the nurse's
    confirmed status."""
    if mode == "PROVISIONAL":
        age_used = stated_age_years
        status_used = patient["pregnancy_status"] if patient else "NOT_APPLICABLE"
    else:
        age_used = full_years_between(patient["dob"], store.clock.date()) if patient else 0
        status_used = confirmed_pregnancy_status
    return age_used, status_used


def assessment_acuity_score(protocol, age_used, status_used, red_flag_count):
    age_points = age_modifier_points(age_used, protocol)
    preg_points = pregnancy_modifier_points(status_used, protocol)
    flag_points = red_flag_points(red_flag_count)
    raw = protocol["base_severity"] + age_points + preg_points + flag_points
    score = min(100, max(0, raw))
    return {
        "age_modifier_points": age_points,
        "pregnancy_modifier_points": preg_points,
        "red_flag_points": flag_points,
        "acuity_score": score,
    }


# ---------------------------------------------------------------------------
# 6. disposition_recommendation — five ordered steps
# ---------------------------------------------------------------------------
def band_acuity(acuity_score):
    if acuity_score >= BAND_EMERGENCY_911_MIN:
        return "EMERGENCY_911"
    if acuity_score >= BAND_ED_NOW_MIN:
        return "ED_NOW"
    if acuity_score >= BAND_URGENT_CARE_24H_MIN:
        return "URGENT_CARE_24H"
    if acuity_score >= BAND_OFFICE_APPT_72H_MIN:
        return "OFFICE_APPT_72H"
    return "HOME_CARE"


def disposition_recommendation(assessment, protocol, call):
    # STEP 1 — band the score.
    level = band_acuity(assessment["acuity_score"])
    # STEP 2 — hard protocol override.
    if protocol["emergency_override"] and assessment["red_flag_count"] >= 1:
        level = "EMERGENCY_911"
    # STEP 3 — infant floor.
    if assessment["age_years_used"] < 1 and level in ("OFFICE_APPT_72H", "HOME_CARE"):
        level = "URGENT_CARE_24H"
    # STEP 4 — after-hours floor.
    if call["is_after_hours"] and level == "OFFICE_APPT_72H":
        level = "URGENT_CARE_24H"
    # STEP 5 — protocol floor, compared on the severity scale.
    floor = protocol["min_disposition_level"]
    if LEVEL_ORDINAL[level] < LEVEL_ORDINAL[floor]:
        level = floor
    return level


# ---------------------------------------------------------------------------
# 7. call_advice_fee — round once per call, then accumulate
# ---------------------------------------------------------------------------
def call_advice_fee(handle_minutes, per_minute_rate_millicents):
    billable = ceil_to_multiple(handle_minutes, BILLING_INCREMENT_MINUTES)
    cents = round_half_up_cents(billable * per_minute_rate_millicents, 1000)
    return billable, cents


# ---------------------------------------------------------------------------
# 8. practice_after_hours_invoice — five steps, tier keyed on step one
# ---------------------------------------------------------------------------
def practice_after_hours_invoice(practice):
    advice_subtotal_cents = practice["advice_fee_accrued_cents"]
    escalation_gross_cents = practice["escalated_callback_count"] * ESCALATION_UNIT_CENTS
    if advice_subtotal_cents <= 99:
        coverage_credit_pct = 0
    elif advice_subtotal_cents <= 999:
        coverage_credit_pct = 5
    else:
        coverage_credit_pct = 10
    coverage_credit_cents = round_half_up_cents(
        escalation_gross_cents * coverage_credit_pct, 100)
    invoice_total_cents = (advice_subtotal_cents + escalation_gross_cents
                           - coverage_credit_cents)
    return {
        "advice_subtotal_cents": advice_subtotal_cents,
        "billed_advice_minutes_total": practice["billed_advice_minutes_total"],
        "escalated_callback_count": practice["escalated_callback_count"],
        "escalation_gross_cents": escalation_gross_cents,
        "coverage_credit_pct": coverage_credit_pct,
        "coverage_credit_cents": coverage_credit_cents,
        "invoice_total_cents": invoice_total_cents,
    }


# ---------------------------------------------------------------------------
# 9. outcome_variance_classification
# ---------------------------------------------------------------------------
def outcome_variance_classification(reported_outcome, final_level):
    outcome_ordinal = OUTCOME_ORDINAL[reported_outcome]
    level_ordinal = LEVEL_ORDINAL[final_level]
    diff = outcome_ordinal - level_ordinal
    if diff == 0:
        variance_class = "CONCORDANT"
        points = 0
    elif diff >= 1:
        variance_class = "UNDERTRIAGE"
        points = abs(diff) * 7
    else:
        variance_class = "OVERTRIAGE"
        points = abs(diff) * 3
    return {
        "outcome_ordinal": outcome_ordinal,
        "disposition_level_ordinal": level_ordinal,
        "variance_class": variance_class,
        "variance_severity_points": points,
    }


# ---------------------------------------------------------------------------
# 10. practice_concordance_rate — two readings of the same input set
# ---------------------------------------------------------------------------
def concordance_input_set(practice):
    """Audit records created in [audit_period_start_utc, clock) whose
    disposition is still live advice and whose call belongs to this practice."""
    period_start = practice["audit_period_start_utc"]
    rows = []
    for record in ordered(store.audit_records):
        if record["created_at"] >= store.clock:
            continue
        if period_start is not None and record["created_at"] < period_start:
            continue
        disposition = store.dispositions.get(record["disposition_id"])
        if disposition is None:
            continue
        if disposition["advice_status"] not in ("AUTHORIZED", "OVERRIDDEN"):
            continue
        call = store.calls.get(disposition["call_id"])
        if call is None or call["practice_id"] != practice["id"]:
            continue
        rows.append(record)
    return rows


def practice_concordance_summary(practice):
    rows = concordance_input_set(practice)
    audited_count = len(rows)
    strict = 0
    band_tolerant = 0
    undertriage = 0
    overtriage = 0
    points_total = 0
    for record in rows:
        gap = record["outcome_ordinal"] - record["disposition_level_ordinal"]
        if gap == 0:
            strict += 1
        if abs(gap) <= 1:
            band_tolerant += 1
        if record["variance_class"] == "UNDERTRIAGE":
            undertriage += 1
        elif record["variance_class"] == "OVERTRIAGE":
            overtriage += 1
        points_total += record["variance_severity_points"]
    if audited_count == 0:
        strict_pct = 0.0
        band_pct = 0.0
    else:
        strict_pct = round_half_up_1dp(100 * strict, audited_count)
        band_pct = round_half_up_1dp(100 * band_tolerant, audited_count)
    return {
        "audited_count": audited_count,
        "concordant_count_strict": strict,
        "concordant_count_band_tolerant": band_tolerant,
        "concordance_rate_strict_pct": strict_pct,
        "concordance_rate_band_tolerant_pct": band_pct,
        "undertriage_count": undertriage,
        "overtriage_count": overtriage,
        "variance_severity_points_total": points_total,
        "open_variance_count": practice["open_variance_count"],
        "compliance_posture": practice["compliance_posture"],
    }


# ---------------------------------------------------------------------------
# 11. nurse_assignment_selector — a licensure filter plus a deterministic rank
# ---------------------------------------------------------------------------
def nurse_is_eligible(nurse, call):
    if nurse["intake_eligibility"] != "ON_ROTATION":
        return False
    if not nurse_has_active_license(nurse["id"], call["caller_state_code"]):
        return False
    if not nurse_on_running_shift(nurse["id"]):
        return False
    if nurse["active_call_load"] >= nurse["max_concurrent_calls"]:
        return False
    return True


def nurse_assignment_candidates(call):
    candidates = [n for n in ordered(store.nurses) if nurse_is_eligible(n, call)]
    candidates.sort(key=lambda n: (n["active_call_load"],
                                   -n["seniority_level"],
                                   n["created_at"],
                                   n["_seq"]))
    return candidates


def select_nurse(call):
    candidates = nurse_assignment_candidates(call)
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# 12. callback_requirement
# ---------------------------------------------------------------------------
def callback_requirement(final_level, call, practice, base_instant):
    ordinal = LEVEL_ORDINAL[final_level]
    requires_callback = not (final_level == "HOME_CARE" and call["is_after_hours"] is False)
    if ordinal >= HIGH_RISK_MIN_LEVEL_ORDINAL:
        risk_class = "HIGH_RISK"
    elif call["is_after_hours"] and ordinal <= 2:
        risk_class = "NEXT_DAY"
    else:
        risk_class = "STANDARD"
    if risk_class == "HIGH_RISK":
        due_by = add_hours(base_instant, HIGH_RISK_DUE_HOURS)
        max_attempts = HIGH_RISK_MAX_ATTEMPTS
    elif risk_class == "STANDARD":
        due_by = add_hours(base_instant, STANDARD_DUE_HOURS)
        max_attempts = STANDARD_MAX_ATTEMPTS
    else:
        due_by = next_day_at(base_instant, practice["office_open_utc_hhmm"])
        max_attempts = STANDARD_MAX_ATTEMPTS
    return {
        "requires_callback": requires_callback,
        "risk_class": risk_class,
        "due_by_utc": due_by,
        "max_attempts": max_attempts,
    }


# ---------------------------------------------------------------------------
# 13. staffing_adequacy
# ---------------------------------------------------------------------------
def staffing_adequacy(state_code, window_start, window_end):
    offered_call_count = 0
    for call in store.calls.values():
        if call["caller_state_code"] != state_code:
            continue
        if window_start <= call["created_at"] < window_end:
            offered_call_count += 1

    required_nurse_minutes = ceil_div(
        offered_call_count * AVG_HANDLE_MINUTES * 100, TARGET_OCCUPANCY_PCT)

    licensed_nurse_ids = set()
    window_start_date = window_start.date()
    for lic in store.licenses.values():
        if lic["state_code"] != state_code:
            continue
        if lic["expires_on"] >= window_start_date:
            licensed_nurse_ids.add(lic["nurse_id"])

    scheduled_nurse_minutes = 0
    for shift in store.shifts.values():
        if shift["nurse_id"] not in licensed_nurse_ids:
            continue
        scheduled_nurse_minutes += overlap_minutes(
            shift["start_utc"], shift["end_utc"], window_start, window_end)

    if required_nurse_minutes == 0:
        ratio = 100.0
    else:
        ratio = round_half_up_1dp(100 * scheduled_nurse_minutes, required_nurse_minutes)

    if ratio >= 100.0:
        posture = "ADEQUATE"
    elif ratio >= 80.0:
        posture = "STRAINED"
    else:
        posture = "CRITICAL"

    return {
        "offered_call_count": offered_call_count,
        "required_nurse_minutes": required_nurse_minutes,
        "scheduled_nurse_minutes": scheduled_nurse_minutes,
        "adequacy_ratio_pct": ratio,
        "staffing_posture": posture,
        "licensed_nurse_count": len(licensed_nurse_ids),
    }

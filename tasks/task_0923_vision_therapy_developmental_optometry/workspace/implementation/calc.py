"""The eighteen calculations of §3, with the rounding discipline of §2.6."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import config
from store import db, latest, parse_date, parse_instant, now


# ------------------------------------------------------------- numerics ---
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def r2(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r1(value):
    return D(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def f2(value):
    return float(r2(value))


def f1(value):
    return float(r1(value))


def clamp(value, low, high):
    value = D(value)
    if value < D(low):
        return D(low)
    if value > D(high):
        return D(high)
    return value


def whole_months(from_date, to_date):
    """Whole calendar months elapsed, floored; the same day-of-month completes
    the month.  Never negative."""
    if from_date is None or to_date is None:
        return 0
    months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month)
    if to_date.day < from_date.day:
        months -= 1
    return max(months, 0)


def months_between(from_date, to_date):
    """Signed whole-month distance used by the VISION frequency test."""
    if from_date is None or to_date is None:
        return 0
    months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month)
    if to_date.day < from_date.day:
        months -= 1
    return months


# -------------------------------------------------- 1. patient_age_years ---
def patient_age_years(dob_text, encounter_text):
    dob = parse_date(dob_text)
    enc = parse_date(encounter_text)
    if dob is None or enc is None:
        return 0
    years = enc.year - dob.year
    if (enc.month, enc.day) < (dob.month, dob.day):
        years -= 1
    return years


# ------------------------ 2. accommodative_amplitude_reference_band --------
def amplitude_band(purpose, age):
    if purpose == "DISCHARGE_READINESS":
        variant = "FUNCTIONAL"
        minimum = r2(D(config.FUNCTIONAL_MIN_INTERCEPT_D)
                     - D(config.FUNCTIONAL_MIN_SLOPE_D_PER_YEAR) * D(age))
        high = r2(minimum + D(config.FUNCTIONAL_BAND_WIDTH_D))
    else:
        variant = "STANDARD"
        minimum = r2(D(config.HOFSTETTER_STANDARD_INTERCEPT_D)
                     - D(config.HOFSTETTER_STANDARD_SLOPE_D_PER_YEAR) * D(age))
        high = r2(minimum + D(config.STANDARD_BAND_WIDTH_D))
    return variant, minimum, high


def apply_measurement_band(measurement, assessment):
    """Writes reference_variant / expected_min_value / expected_band_high /
    within_reference_band / diagnostic_flag on an amplitude row; every other
    metric_code keeps nulls and within_reference_band false."""
    if measurement["metric_code"] != "ACCOMMODATIVE_AMPLITUDE":
        measurement["reference_variant"] = None
        measurement["expected_min_value"] = None
        measurement["expected_band_high"] = None
        measurement["within_reference_band"] = False
        return
    variant, minimum, high = amplitude_band(assessment["purpose"], assessment["patient_age_years"])
    amp = D(measurement["amplitude_d"])
    measurement["reference_variant"] = variant
    measurement["expected_min_value"] = float(minimum)
    measurement["expected_band_high"] = float(high)
    measurement["within_reference_band"] = bool(minimum <= amp <= high)
    measurement["diagnostic_flag"] = bool(amp < minimum)


# --------------------------------------------- helpers over measurements ---
def measurements_of(assessment_id):
    rows = [m for m in db.measurements.values() if m["assessment_id"] == assessment_id]
    rows.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return rows


def latest_metric(assessment_id, metric_code):
    rows = [m for m in measurements_of(assessment_id) if m["metric_code"] == metric_code]
    return latest(rows) if rows else None


# ---------------------------------------- 3. npc_threshold_evaluation ------
def finalize_clinical_flags(assessment):
    """Refreshes every child row's derived fields, then writes the three
    assessment-level booleans (PRD §3.2)."""
    rows = measurements_of(assessment["id"])
    for row in rows:
        apply_measurement_band(row, assessment)

    npc = latest_metric(assessment["id"], "NPC")
    diagnostic_breach = False
    discharge_pass = False
    if npc is not None:
        diagnostic_breach = (D(npc["npc_break_cm"]) > D(config.NPC_BREAK_DIAGNOSTIC_CM)
                             or D(npc["npc_recovery_cm"]) > D(config.NPC_RECOVERY_DIAGNOSTIC_CM))
        discharge_pass = (D(npc["npc_break_cm"]) <= D(config.NPC_BREAK_DISCHARGE_CM)
                          and D(npc["npc_recovery_cm"]) <= D(config.NPC_RECOVERY_DISCHARGE_CM))
        npc["diagnostic_flag"] = bool(diagnostic_breach)

    amp = latest_metric(assessment["id"], "ACCOMMODATIVE_AMPLITUDE")
    # therapy_indicated reads the amplitude row's OWN variant minimum, per the
    # PRD §3.1/§3.2 prose ("evaluated against whichever variant's minimum the
    # row carries"), which governs over the shorter field-summary wording.
    assessment["therapy_indicated"] = bool(
        diagnostic_breach or (amp is not None and bool(amp.get("diagnostic_flag")))
    )
    assessment["discharge_metric_met"] = bool(
        discharge_pass
        and (amp is None or D(amp["amplitude_d"]) >= D(amp["expected_min_value"]))
    )
    assessment["red_flag_present"] = any(bool(r.get("red_flag")) for r in rows)


# ----------------------------------------- 4/5. session units and charge ---
def session_billable_units(procedure_code, timed_minutes):
    if procedure_code == "HOME_PRACTICE":
        return 0
    if procedure_code == "FLAT_ORTHOPTIC_TRAINING":
        return config.FLAT_UNIT_COUNT
    minutes = timed_minutes or 0
    if minutes <= config.TIMED_STEP_0_UPPER_MINUTES:
        return 0
    if minutes <= config.TIMED_STEP_1_UPPER_MINUTES:
        return 1
    if minutes <= config.TIMED_STEP_2_UPPER_MINUTES:
        return 2
    if minutes <= config.TIMED_STEP_3_UPPER_MINUTES:
        return 3
    if minutes <= config.TIMED_STEP_4_UPPER_MINUTES:
        return 4
    if minutes <= config.TIMED_STEP_5_UPPER_MINUTES:
        return 5
    return config.UNITS_CAP_PER_SESSION


def rate_for(procedure_code):
    if procedure_code == "TIMED_THERAPEUTIC_ACTIVITY":
        return D(config.RATE_TIMED_THERAPEUTIC_ACTIVITY)
    if procedure_code == "FLAT_ORTHOPTIC_TRAINING":
        return D(config.RATE_FLAT_ORTHOPTIC_TRAINING)
    if procedure_code == "EVALUATION_ENCOUNTER":
        return D(config.RATE_EVALUATION_ENCOUNTER)
    return D("0.00")


def charge_amount(units, procedure_code):
    return f2(D(units) * rate_for(procedure_code))


# --------------------------- 7. weighted_cumulative_therapy_minutes --------
def weighted_minutes(session):
    minutes = session.get("timed_minutes")
    if minutes is None:
        return 0.0
    if session["modality"] == "IN_OFFICE":
        return float(minutes)
    return f1(D(minutes) * D(config.HOME_MINUTE_WEIGHT))


def recompute_cumulative_minutes(plan):
    total = D("0")
    for s in db.sessions.values():
        if s["plan_id"] != plan["id"]:
            continue
        if s["schedule_status"] in ("COMPLETED", "ATTESTED"):
            total += D(s.get("weighted_minutes") or 0.0)
    plan["cumulative_therapy_minutes"] = f1(total)


# --------------------------------------------- 8. home_compliance_pct ------
def compute_home_compliance(plan):
    window_end = now()
    window_start = window_end - timedelta(days=config.COMPLIANCE_WINDOW_DAYS)

    changed_raw = plan.get("prescription_changed_at")
    per_week = plan.get("prescribed_home_sessions_per_week")
    if changed_raw:
        changed = parse_instant(changed_raw)
        if changed is not None and changed > window_start:
            previous = plan.get("previous_prescribed_home_sessions_per_week")
            if previous is not None:
                per_week = previous

    denominator = D(per_week or 0) * D(config.COMPLIANCE_WINDOW_DAYS) / D(7)
    if denominator == 0:
        return 0.0

    numerator = 0
    for s in db.sessions.values():
        if s["plan_id"] != plan["id"] or s["modality"] != "HOME":
            continue
        if s["schedule_status"] != "ATTESTED":
            continue
        performed = parse_instant(s.get("performed_at"))
        if performed is None:
            continue
        if window_start < performed <= window_end:
            numerator += 1
    pct = D(numerator) / denominator * D(100)
    if pct > D(100):
        pct = D(100)
    return f2(pct)


def refresh_home_compliance(plan):
    plan["home_compliance_pct"] = compute_home_compliance(plan)
    return plan["home_compliance_pct"]


# ------------------------------------------ 9. symptom_improvement_pct -----
def symptom_improvement_pct(plan, assessment):
    baseline = plan.get("baseline_ciss_score") if plan else None
    current = latest_metric(assessment["id"], "SYMPTOM_SURVEY")
    if baseline is None or D(baseline) == 0 or current is None:
        return 0.0
    value = (D(baseline) - D(current["ciss_score"])) / D(baseline) * D(100)
    return f2(clamp(value, 0, 100))


# ----------------------------------------- 10. composite_progress_score ----
def _component(numerator, divisor, floor):
    if divisor < D(floor):
        divisor = D(floor)
    return r2(clamp(numerator / divisor * D(100), 0, 100))


def composite_progress_score(patient, plan, assessment, sym_pct):
    aid = assessment["id"]
    npc = latest_metric(aid, "NPC")
    amp = latest_metric(aid, "ACCOMMODATIVE_AMPLITUDE")
    verg = latest_metric(aid, "VERGENCE_BASE_OUT")
    acu = latest_metric(aid, "VISUAL_ACUITY")

    npc_pct = D("0.00")
    if npc is not None and plan.get("baseline_npc_break_cm") is not None:
        base = D(plan["baseline_npc_break_cm"])
        npc_pct = _component(base - D(npc["npc_break_cm"]),
                             base - D(config.NPC_BREAK_DISCHARGE_CM), "0.1")

    amp_pct = D("0.00")
    if (amp is not None and plan.get("baseline_amplitude_d") is not None
            and amp.get("expected_min_value") is not None):
        base = D(plan["baseline_amplitude_d"])
        amp_pct = _component(D(amp["amplitude_d"]) - base,
                             D(amp["expected_min_value"]) - base, "0.1")

    verg_pct = D("0.00")
    if verg is not None and plan.get("baseline_vergence_bo_break_pd") is not None:
        base = D(plan["baseline_vergence_bo_break_pd"])
        verg_pct = _component(D(verg["vergence_bo_break_pd"]) - base,
                              D(config.VERGENCE_GOAL_PD) - base, "0.1")

    acu_pct = D("0.00")
    if acu is not None and plan.get("baseline_acuity_logmar") is not None:
        base = D(plan["baseline_acuity_logmar"])
        acu_pct = _component(base - D(acu["acuity_logmar"]),
                             base - D(config.ACUITY_GOAL_LOGMAR), "0.01")

    sym = D(sym_pct)
    diagnosis = patient["diagnosis_category"]
    if diagnosis == "AMBLYOPIA":
        score = (D(config.ACUITY_VARIANT_W_ACUITY) * acu_pct
                 + D(config.ACUITY_VARIANT_W_NPC) * npc_pct
                 + D(config.ACUITY_VARIANT_W_SYMPTOM) * sym)
    elif diagnosis == "CONVERGENCE_INSUFFICIENCY":
        score = (D(config.CI_W_NPC) * npc_pct + D(config.CI_W_AMP) * amp_pct
                 + D(config.CI_W_VERG) * verg_pct + D(config.CI_W_SYMPTOM) * sym)
    elif diagnosis == "ACCOMMODATIVE_DYSFUNCTION":
        score = (D(config.AD_W_NPC) * npc_pct + D(config.AD_W_AMP) * amp_pct
                 + D(config.AD_W_VERG) * verg_pct + D(config.AD_W_SYMPTOM) * sym)
    else:
        score = (D(config.OM_W_NPC) * npc_pct + D(config.OM_W_AMP) * amp_pct
                 + D(config.OM_W_VERG) * verg_pct + D(config.OM_W_SYMPTOM) * sym)
    return f2(score)


# --------------------------------------------------- 11. plateau logic -----
def prior_signed_reassessment(plan_id, exclude_id):
    rows = [a for a in db.assessments.values()
            if a["plan_id"] == plan_id
            and a["assessment_type"] == "REASSESSMENT"
            and a["status"] == "SIGNED"
            and a["id"] != exclude_id
            and a.get("signed_at")]
    return latest(rows, "signed_at") if rows else None


# ------------------------------- 13. discharge_readiness_determination -----
def discharge_readiness(plan):
    """Both variants read only SIGNED assessments, so an assessment being
    finalized never counts toward the recomputation its own finalize triggers."""
    if plan is None:
        return False
    if plan.get("discharge_criteria_mode") == "METRIC":
        rows = [a for a in db.assessments.values()
                if a["plan_id"] == plan["id"] and a["purpose"] == "DISCHARGE_READINESS"
                and a["status"] == "SIGNED" and a.get("signed_at")]
        chosen = latest(rows, "signed_at") if rows else None
        return bool(chosen is not None and chosen.get("discharge_metric_met"))
    rows = [a for a in db.assessments.values()
            if a["plan_id"] == plan["id"] and a["assessment_type"] == "REASSESSMENT"
            and a["status"] == "SIGNED" and a.get("signed_at")]
    chosen = latest(rows, "signed_at") if rows else None
    if chosen is None:
        return False
    score = chosen.get("composite_progress_score")
    symptom = chosen.get("symptom_improvement_pct")
    if score is None or symptom is None:
        return False
    return bool(D(score) >= D(config.DISCHARGE_SCORE_THRESHOLD)
                and D(symptom) >= D(config.DISCHARGE_SYMPTOM_IMPROVEMENT_PCT))


# ------------------------------------------------- 14. kit_damage_fee ------
_CONDITION_MULTIPLIER = {
    "GOOD": config.CONDITION_MULTIPLIER_GOOD,
    "FAIR": config.CONDITION_MULTIPLIER_FAIR,
    "DAMAGED": config.CONDITION_MULTIPLIER_DAMAGED,
    "LOST": config.CONDITION_MULTIPLIER_LOST,
}


def kit_damage_fee(item, returned_condition, return_date):
    in_service = parse_date(item["in_service_date"])
    months = whole_months(in_service, return_date)
    life = item["useful_life_months"]
    capped = min(months, life)
    cost = D(item["replacement_cost"])
    straight_line = cost * (D(1) - D(capped) / D(life))
    salvage = cost * D(config.KIT_SALVAGE_FLOOR_RATE)
    depreciated = straight_line if straight_line > salvage else salvage
    multiplier = D(_CONDITION_MULTIPLIER[returned_condition])
    return f2(depreciated * multiplier)


# ---------------------------------------------- 15. occlusion_daily_dose ---
_OCCLUSION_LADDER = {
    ("YOUNG", "MILD"): config.OCCLUSION_YOUNG_MILD_HOURS,
    ("YOUNG", "MODERATE"): config.OCCLUSION_YOUNG_MODERATE_HOURS,
    ("YOUNG", "SEVERE"): config.OCCLUSION_YOUNG_SEVERE_HOURS,
    ("SCHOOL", "MILD"): config.OCCLUSION_SCHOOL_MILD_HOURS,
    ("SCHOOL", "MODERATE"): config.OCCLUSION_SCHOOL_MODERATE_HOURS,
    ("SCHOOL", "SEVERE"): config.OCCLUSION_SCHOOL_SEVERE_HOURS,
    ("OLDER", "MILD"): config.OCCLUSION_OLDER_MILD_HOURS,
    ("OLDER", "MODERATE"): config.OCCLUSION_OLDER_MODERATE_HOURS,
    ("OLDER", "SEVERE"): config.OCCLUSION_OLDER_SEVERE_HOURS,
}


def occlusion_age_band(age):
    if age < config.OCCLUSION_YOUNG_UPPER_AGE:
        return "YOUNG"
    if age <= config.OCCLUSION_SCHOOL_UPPER_AGE:
        return "SCHOOL"
    return "OLDER"


def occlusion_daily_dose(age, severity):
    band = occlusion_age_band(age)
    raw = _OCCLUSION_LADDER[(band, severity)]
    return band, min(raw, config.OCCLUSION_MAX_DAILY_HOURS)


# --------------------------------------------- 17. occlusion adherence -----
def adherence_pct(logged_days, adherent_days):
    if logged_days == 0:
        return 0.0
    return f2(D(adherent_days) / D(logged_days) * D(100))


# ------------------------------ 18. therapist_daily_scheduled_minutes ------
def interval_minutes(start_raw, end_raw):
    start = parse_instant(start_raw)
    end = parse_instant(end_raw)
    if start is None or end is None:
        return 0
    return int((end - start).total_seconds() // 60)


def therapist_scheduled_minutes(therapist_id, day):
    total = 0
    for s in db.sessions.values():
        if s.get("therapist_id") != therapist_id or s["modality"] != "IN_OFFICE":
            continue
        if s["schedule_status"] not in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW"):
            continue
        start = parse_instant(s.get("scheduled_start_at"))
        if start is None or start.date() != day:
            continue
        total += interval_minutes(s["scheduled_start_at"], s["scheduled_end_at"])
    return total

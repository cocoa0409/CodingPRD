"""Pre-anesthesia risk scoring (calculations.pre_anesthesia_risk_score)."""
from decimal import Decimal

from db import clock_dt
from services.domain import (BAND_ELEVATED_FLOOR, BAND_HIGH_FLOOR,
                             BAND_PROHIBITIVE_FLOOR, COMORBIDITY_POINT_CAP,
                             HEAVY_WEIGHT_KG, LEVEL_MULTIPLIER,
                             NPO_SOLIDS_MINUTES_MIN, get_patient)
from timeutil import dec, parse_date, r2, whole_years


def patient_age_years(patient):
    """Whole years from date_of_birth to the current logical clock."""
    dob = parse_date(patient.get("date_of_birth"))
    if dob is None:
        return 0
    return max(0, whole_years(dob, clock_dt()))


def band_for(score):
    value = Decimal(str(score))
    if value < BAND_ELEVATED_FLOOR:
        return "LOW"
    if value < BAND_HIGH_FLOOR:
        return "ELEVATED"
    if value < BAND_PROHIBITIVE_FLOOR:
        return "HIGH"
    return "PROHIBITIVE"


def core_score(evaluation, case, patient):
    base_points = 10 * int(evaluation["asa_class_recorded"])
    airway_points = 8 * max(0, int(evaluation["airway_class_recorded"]) - 2)
    age = patient_age_years(patient)
    if age >= 70:
        age_points = 6
    elif age < 3:
        age_points = 4
    else:
        age_points = 0
    comorbidity_points = min(COMORBIDITY_POINT_CAP, 3 * int(evaluation.get("comorbidity_count") or 0))
    weight_points = 5 if dec(patient["weight_kg"]) >= HEAVY_WEIGHT_KG else 0
    subtotal = Decimal(base_points + airway_points + age_points + comorbidity_points + weight_points)
    multiplier = LEVEL_MULTIPLIER[case["planned_anesthesia_level"]]
    return r2(subtotal * multiplier)


def apply_provisional(evaluation, case):
    """Provisional variant: the multiplied core score, with the band it implies."""
    patient = get_patient(case["patient_id"])
    score = core_score(evaluation, case, patient)
    evaluation["provisional_risk_score"] = float(score)
    evaluation["risk_band"] = band_for(score)
    return score


def final_penalty(evaluation, case, practice):
    penalty = 0
    npo_solids = evaluation.get("npo_solids_minutes")
    if npo_solids is not None and int(npo_solids) < NPO_SOLIDS_MINUTES_MIN:
        penalty += 15
    if not evaluation.get("escort_confirmed") and case["planned_anesthesia_level"] != "LOCAL_ONLY":
        penalty += 10
    if practice.get("sedation_privilege_state") == "RESTRICTED":
        penalty += 6
    return penalty


def apply_final(evaluation, case, practice):
    """Final variant: flat penalties added AFTER the multiplier rounding."""
    patient = get_patient(case["patient_id"])
    core = core_score(evaluation, case, patient)
    score = r2(core + Decimal(final_penalty(evaluation, case, practice)))
    evaluation["final_risk_score"] = float(score)
    evaluation["risk_band"] = band_for(score)
    return score

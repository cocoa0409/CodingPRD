"""Every derived value and calculation (SCAFFOLD 1.4, PRD 2.5-2.9, 3.x).

Nothing here writes to the store except the small `recompute_*` helpers that
refresh a row's own computed columns; all unit-level figures are pure functions
recomputed on every read and before every decision that consults them.
"""
import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import clock
from db import db, ordered

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
LEVELS = ["LEVEL_I", "LEVEL_II", "LEVEL_III", "LEVEL_IV"]
HOSPITAL_TYPES = ["REGIONAL_CENTER", "COMMUNITY"]
DESIGNATION_STATUSES = ["PROVISIONAL", "DESIGNATED", "CONDITIONAL", "SUSPENDED"]
CENSUS_POSTURES = ["OPEN", "CONSTRAINED", "CLOSED"]
CREDENTIAL_CODES = ["NEO_BOARD", "NNP", "RN_NICU_CORE", "RT_NEO", "TRANSPORT_RN",
                   "LACTATION_IBCLC", "DEV_CARE_CERT"]
EQUIPMENT_CODES = ["CONVENTIONAL_VENT", "HFOV", "INHALED_NO",
                   "THERAPEUTIC_HYPOTHERMIA", "TRANSPORT_ISOLETTE", "ECMO_CIRCUIT"]
OUT_OF_SERVICE_REASONS = ["BIOMED_FAULT", "RECALL", "CONTAMINATION",
                          "AWAITING_PARTS", "SCHEDULED_SERVICE"]
REFERRAL_KINDS = ["INBOUND_NEONATAL", "MATERNAL_ANTENATAL", "BACK_TRANSFER"]
SUPPORT_MODALITIES = ["ROOM_AIR", "CPAP", "CONVENTIONAL_VENT", "HFOV",
                      "INHALED_NO", "ECMO_CONSULT"]
DIAGNOSES = ["RDS_SEVERE", "HIE_MODERATE", "PROM", "CHD_DUCTAL", "SURGICAL_NEC"]
TRANSPORT_MODES = ["GROUND", "ROTOR_WING", "FIXED_WING"]
ABORT_REASONS = ["WEATHER", "CREW_UNAVAILABLE", "PATIENT_DEMISE"]
DONOR_TYPES = ["MOTHERS_OWN", "DONOR_PASTEURIZED"]
DISCARD_REASONS = ["EXPIRED", "LABEL_MISMATCH", "QUARANTINE_DISPOSAL", "FAMILY_REQUEST"]
INFECTION_EVENTS = ["SUSPECT", "CONFIRM_CLABSI", "RESOLVE"]
DISPOSITIONS = ["HOME", "DECEASED"]
DECLINE_REASONS = ["NO_CAPABILITY", "CLINICAL_DECLINE"]

OCCUPYING_CARE_STATUSES = ("ADMITTED", "STABILIZED", "BACK_TRANSFER_READY",
                           "BACK_TRANSFER_REQUIRED")
IN_FLIGHT_RUN_STATUSES = ("GROUND_ROLLING", "AIR_LAUNCHED", "ON_SCENE",
                          "STABILIZING", "EN_ROUTE")
NON_TERMINAL_RUN_STATUSES = ("ACTIVATED",) + IN_FLIGHT_RUN_STATUSES

D0 = Decimal("0")
D1 = Decimal("1")
D100 = Decimal("100")


# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------
def q1(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def floor_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# --------------------------------------------------------------------------
# Level ladder (PRD 2.7)
# --------------------------------------------------------------------------
def rank(level):
    try:
        return LEVELS.index(level) + 1
    except ValueError:
        return 1


def level_of_rank(value):
    value = max(1, min(4, value))
    return LEVELS[value - 1]


def higher(*levels):
    best = None
    for level in levels:
        if level is None:
            continue
        if best is None or rank(level) > rank(best):
            best = level
    return best or "LEVEL_I"


def lower(a, b):
    return a if rank(a) <= rank(b) else b


def one_below(level):
    return level_of_rank(rank(level) - 1)


# --------------------------------------------------------------------------
# Clock-derived statuses (PRD 2.5)
# --------------------------------------------------------------------------
def credential_status(cred):
    if cred.get("revoked_at") is not None:
        return "REVOKED"
    if cred["expires_on"] <= clock.now():
        return "EXPIRED"
    return "VALID"


def next_service_due_at(asset):
    return clock.plus_days(asset["last_service_at"], asset["service_interval_days"])


def asset_status(asset):
    if asset.get("out_of_service_at") is not None:
        return "OUT_OF_SERVICE"
    if next_service_due_at(asset) <= clock.now():
        return "SERVICE_DUE"
    return "IN_SERVICE"


# --------------------------------------------------------------------------
# Collections by unit
# --------------------------------------------------------------------------
def unit_credentials(unit_id):
    return [c for c in db.credentials.values() if c["unit_id"] == unit_id]


def unit_assets(unit_id):
    return [a for a in db.assets.values() if a["unit_id"] == unit_id]


def unit_admissions(unit_id):
    return [a for a in db.admissions.values() if a["unit_id"] == unit_id]


def unit_reservations(unit_id):
    return [r for r in db.reservations.values() if r["unit_id"] == unit_id]


def unit_escalations(unit_id):
    return [e for e in db.escalations.values() if e["unit_id"] == unit_id]


def standard_for_level(level):
    for standard in db.standards.values():
        if standard["level"] == level:
            return standard
    return None


def referral_reservations(referral_id):
    return [r for r in db.reservations.values() if r["referral_id"] == referral_id]


def admission_batches(admission_id):
    return [b for b in db.milk_batches.values() if b["admission_id"] == admission_id]


# --------------------------------------------------------------------------
# Unit capability (PRD 2.7)
# --------------------------------------------------------------------------
def _held_credential_codes(unit_id):
    codes = set()
    for cred in unit_credentials(unit_id):
        if credential_status(cred) == "VALID" and cred["fte"] >= Decimal("0.5"):
            codes.add(cred["credential_code"])
    return codes


def _in_service_equipment_codes(unit_id):
    codes = set()
    for asset in unit_assets(unit_id):
        if asset_status(asset) == "IN_SERVICE":
            codes.add(asset["equipment_code"])
    return codes


def satisfies_standard(unit, standard, cred_codes=None, equip_codes=None):
    if cred_codes is None:
        cred_codes = _held_credential_codes(unit["id"])
    if equip_codes is None:
        equip_codes = _in_service_equipment_codes(unit["id"])
    for code in standard["required_credential_codes"]:
        if code not in cred_codes:
            return False
    for code in standard["required_equipment_codes"]:
        if code not in equip_codes:
            return False
    return True


def capability_level(unit):
    cred_codes = _held_credential_codes(unit["id"])
    equip_codes = _in_service_equipment_codes(unit["id"])
    best = "LEVEL_I"
    for standard in db.standards.values():
        if satisfies_standard(unit, standard, cred_codes, equip_codes):
            if rank(standard["level"]) > rank(best):
                best = standard["level"]
    return best


def effective_level(unit):
    return lower(unit["designated_level"], capability_level(unit))


def staffing_compliant(unit):
    standard = standard_for_level(unit["designated_level"])
    if standard is None:
        return True
    cred_codes = _held_credential_codes(unit["id"])
    return all(code in cred_codes for code in standard["required_credential_codes"])


def equipment_compliant(unit):
    standard = standard_for_level(unit["designated_level"])
    if standard is None:
        return True
    equip_codes = _in_service_equipment_codes(unit["id"])
    return all(code in equip_codes for code in standard["required_equipment_codes"])


# --------------------------------------------------------------------------
# Bed ledger (PRD 2.8)
# --------------------------------------------------------------------------
def escalation_bed_count(unit):
    total = 0
    for esc in unit_escalations(unit["id"]):
        if esc["status"] == "ACTIVE":
            total += esc.get("authorized_beds") or 0
    return total


def occupied_bed_count(unit):
    return len([a for a in unit_admissions(unit["id"])
                if a["care_status"] in OCCUPYING_CARE_STATUSES])


def held_bed_count(unit):
    return len([r for r in unit_reservations(unit["id"]) if r["status"] == "HELD"])


def available_bed_count(unit):
    return (unit["staffed_bed_target"] + escalation_bed_count(unit)
            - occupied_bed_count(unit) - held_bed_count(unit))


def census_posture(unit):
    available = available_bed_count(unit)
    if available <= 0:
        return "CLOSED"
    threshold = floor_int(Decimal(unit["staffed_bed_target"]) * Decimal("0.20"))
    if available <= threshold:
        return "CONSTRAINED"
    return "OPEN"


def staffing_waiver_in_force(unit):
    waiver = Decimal("1.00")
    for esc in unit_escalations(unit["id"]):
        if esc["status"] == "ACTIVE" and esc.get("staffing_waiver_ratio") is not None:
            if esc["staffing_waiver_ratio"] > waiver:
                waiver = esc["staffing_waiver_ratio"]
    return waiver


def required_nurse_count(unit):
    census = [a for a in unit_admissions(unit["id"])
              if a["care_status"] in OCCUPYING_CARE_STATUSES]
    if not census:
        return 0
    waiver = staffing_waiver_in_force(unit)
    total = 0
    for level in LEVELS:
        standard = standard_for_level(level)
        if standard is None:
            continue
        band = len([a for a in census if current_care_level(a) == level])
        if band == 0:
            continue
        denominator = standard["nurse_patient_ratio_denominator"] * waiver
        if denominator <= 0:
            continue
        total += ceil_int(Decimal(band) / denominator)
    return total


def deferral_queue_depth(unit):
    return len([r for r in db.referrals.values()
                if r["receiving_unit_id"] == unit["id"] and r["status"] == "DEFERRED"])


def back_transfer_ready_count(unit):
    return len([a for a in unit_admissions(unit["id"])
                if a["care_status"] == "BACK_TRANSFER_READY"])


def expiring_hold_count(unit):
    horizon = clock.plus_minutes(clock.now(), 60)
    return len([r for r in unit_reservations(unit["id"])
                if r["status"] == "HELD" and r["expires_at"] <= horizon])


# --------------------------------------------------------------------------
# Referral level determination (PRD 3.3)
# --------------------------------------------------------------------------
def weight_term(grams):
    if grams < 1500:
        return "LEVEL_III"
    if grams < 1800:
        return "LEVEL_II"
    return "LEVEL_I"


SUPPORT_TERM = {
    "ROOM_AIR": "LEVEL_I",
    "CPAP": "LEVEL_II",
    "CONVENTIONAL_VENT": "LEVEL_III",
    "HFOV": "LEVEL_III",
    "INHALED_NO": "LEVEL_IV",
    "ECMO_CONSULT": "LEVEL_IV",
}

DIAGNOSIS_TERM = {
    "RDS_SEVERE": "LEVEL_III",
    "HIE_MODERATE": "LEVEL_IV",
    "CHD_DUCTAL": "LEVEL_IV",
    "SURGICAL_NEC": "LEVEL_IV",
    "PROM": "LEVEL_I",
}


def ga_term(weeks):
    if weeks < Decimal("32.0"):
        return "LEVEL_III"
    if weeks < Decimal("35.0"):
        return "LEVEL_II"
    return "LEVEL_I"


def weight_basis_grams(referral):
    if referral["referral_kind"] == "BACK_TRANSFER":
        stored = referral.get("weight_basis_grams")
        if stored is not None:
            return stored
    return referral["birth_weight_grams"]


def referral_levels(referral):
    basis = weight_basis_grams(referral)
    w_term = weight_term(basis)
    s_term = SUPPORT_TERM.get(referral["support_modality"], "LEVEL_I")
    if referral["referral_kind"] == "MATERNAL_ANTENATAL":
        current = higher(s_term, "LEVEL_I")
    else:
        current = higher(s_term, w_term)
    candidates = [current, w_term]
    if referral["referral_kind"] != "BACK_TRANSFER":
        candidates.append(ga_term(referral["gestational_age_weeks"]))
    for code in referral.get("diagnoses") or []:
        if code in DIAGNOSIS_TERM:
            candidates.append(DIAGNOSIS_TERM[code])
    if referral.get("planned_surgery"):
        candidates.append("LEVEL_IV")
    anticipated = higher(*candidates)
    level_basis = ("ANTICIPATED_NEED" if rank(anticipated) > rank(current)
                   else "CURRENT_SUPPORT")
    return current, anticipated, level_basis


def required_level(referral):
    return referral_levels(referral)[1]


def maternal_transfer_preferred(referral):
    return (referral["referral_kind"] == "MATERNAL_ANTENATAL"
            and rank(required_level(referral)) >= 3)


LEVEL_POINTS = {"LEVEL_I": 25, "LEVEL_II": 50, "LEVEL_III": 75, "LEVEL_IV": 100}
KIND_POINTS = {"MATERNAL_ANTENATAL": 100, "INBOUND_NEONATAL": 50, "BACK_TRANSFER": 0}


def prematurity_points(weeks):
    if weeks < Decimal("28.0"):
        return 100
    if weeks < Decimal("32.0"):
        return 75
    if weeks < Decimal("35.0"):
        return 50
    return 25


def weight_points(grams):
    if grams < 1000:
        return 100
    if grams < 1500:
        return 75
    if grams < 1800:
        return 50
    return 25


def triage_priority(referral):
    level = required_level(referral)
    points = (Decimal("0.40") * LEVEL_POINTS[level]
              + Decimal("0.25") * prematurity_points(referral["gestational_age_weeks"])
              + Decimal("0.20") * weight_points(weight_basis_grams(referral))
              + Decimal("0.15") * KIND_POINTS[referral["referral_kind"]])
    return q2(points)


def referral_reservation_id(referral):
    rows = referral_reservations(referral["id"])
    live = [r for r in rows if r["status"] in ("HELD", "OCCUPIED")]
    if live:
        return ordered(live)[-1]["id"]
    if rows:
        return sorted(rows, key=lambda r: (r["held_at"], r["_seq"]))[-1]["id"]
    return None


# --------------------------------------------------------------------------
# Deferral queue promotion ranking (PRD 3.4)
# --------------------------------------------------------------------------
def deferral_pool(unit):
    level_cap = rank(effective_level(unit))
    pool = [r for r in db.referrals.values()
            if r["receiving_unit_id"] == unit["id"]
            and r["status"] == "DEFERRED"
            and rank(required_level(r)) <= level_cap]
    return sorted(pool, key=lambda r: (
        -triage_priority(r),
        0 if maternal_transfer_preferred(r) else 1,
        r["created_at"],
        r["_seq"],
    ))


# --------------------------------------------------------------------------
# Designation compliance score (PRD 3.2)
# --------------------------------------------------------------------------
def compliance_breakdown(unit, requested_level, assigned_nurse_count):
    standard = standard_for_level(requested_level)
    nurses_needed = required_nurse_count(unit)
    if standard is None:
        return {
            "required_nurse_count": nurses_needed,
            "staffing_subscore": q2(D100),
            "equipment_subscore": q2(D100),
            "volume_subscore": q2(D100),
            "compliance_score": q2(D100),
        }
    cred_codes = _held_credential_codes(unit["id"])
    required_creds = standard["required_credential_codes"]
    if required_creds:
        held = len([c for c in required_creds if c in cred_codes])
        coverage = Decimal(held) / Decimal(len(required_creds))
    else:
        coverage = D1

    if nurses_needed == 0:
        ratio_factor = D1
    else:
        ratio_factor = min(D1, Decimal(assigned_nurse_count) / Decimal(nurses_needed))

    staffing = q2(D100 * coverage * ratio_factor)

    equip_codes = _in_service_equipment_codes(unit["id"])
    required_equip = standard["required_equipment_codes"]
    if required_equip:
        held_equip = len([c for c in required_equip if c in equip_codes])
        equipment = q2(D100 * Decimal(held_equip) / Decimal(len(required_equip)))
    else:
        equipment = q2(D100)

    min_volume = Decimal(standard["min_annual_volume"])
    if unit["hospital_type"] != "REGIONAL_CENTER":
        min_volume = min_volume / Decimal(2)
    if min_volume <= 0:
        volume = q2(D100)
    else:
        volume = q2(D100 * min(D1, Decimal(unit["annual_admission_volume"]) / min_volume))

    total = q2(Decimal("0.45") * staffing
               + Decimal("0.35") * equipment
               + Decimal("0.20") * volume)
    if standard["transport_capability_required"] and not unit["transport_capable"]:
        total = min(total, Decimal("69.99"))
    return {
        "required_nurse_count": nurses_needed,
        "staffing_subscore": staffing,
        "equipment_subscore": equipment,
        "volume_subscore": volume,
        "compliance_score": total,
    }


def standard_thresholds(level):
    standard = standard_for_level(level)
    if standard is None:
        return Decimal("0"), Decimal("0")
    return standard["min_compliance_score"], standard["conditional_floor_score"]


# --------------------------------------------------------------------------
# Surge escalation authorization (PRD 3.5)
# --------------------------------------------------------------------------
TIER_WAIVER = {"TIER_1": Decimal("1.10"), "TIER_2": Decimal("1.25"),
               "TIER_3": Decimal("1.50")}
TIER_CAP = {"TIER_1": 2, "TIER_2": 4, "TIER_3": 6}


def census_ratio_at_request(unit, escalation):
    other = 0
    for esc in unit_escalations(unit["id"]):
        if esc["id"] != escalation["id"] and esc["status"] == "ACTIVE":
            other += esc.get("authorized_beds") or 0
    denominator = Decimal(unit["staffed_bed_target"] + other)
    if denominator <= 0:
        return q4(D0)
    return q4(Decimal(occupied_bed_count(unit)) / denominator)


def tier_for_ratio(ratio):
    if ratio >= Decimal("1.00"):
        return "TIER_3"
    if ratio >= Decimal("0.90"):
        return "TIER_2"
    if ratio >= Decimal("0.80"):
        return "TIER_1"
    return None


def rn_core_fte(unit_id):
    total = D0
    for cred in unit_credentials(unit_id):
        if cred["credential_code"] == "RN_NICU_CORE" and credential_status(cred) == "VALID":
            total += cred["fte"]
    return total


def authorized_beds_for(unit, escalation, tier):
    waiver = TIER_WAIVER[tier]
    staffing_capacity = floor_int(rn_core_fte(unit["id"]) * waiver * Decimal(2))
    headroom = staffing_capacity - (occupied_bed_count(unit) + held_bed_count(unit))
    return max(0, min(escalation["requested_beds"], headroom, TIER_CAP[tier]))


# --------------------------------------------------------------------------
# Transport (PRD 3.6)
# --------------------------------------------------------------------------
DECONTAMINATION_MINUTES = {"GROUND": 45, "ROTOR_WING": 90, "FIXED_WING": 90}


def occupation_interval(run):
    start = run["depart_at"]
    if run["status"] == "ARRIVED" and run.get("arrived_at") is not None:
        end = clock.plus_minutes(run["arrived_at"], run["decontamination_minutes"])
    else:
        end = clock.plus_minutes(run["planned_return_at"], run["decontamination_minutes"])
    return start, end


def stabilization(run, referral):
    values = (run.get("temp_c"), run.get("glucose_mg_dl"),
              run.get("mean_bp_mmhg"), run.get("spo2_pct"))
    if any(v is None for v in values):
        return None, False
    temp, glucose, bp, spo2 = values
    score = 100
    if not (Decimal("36.5") <= temp <= Decimal("37.5")):
        score -= 8
    if not glucose >= Decimal("45"):
        score -= 8
    target_bp = referral["gestational_age_weeks"] if referral else Decimal("0")
    if not bp >= target_bp:
        score -= 8
    if not (Decimal("90") <= spo2 <= Decimal("95")):
        score -= 8
    return score, score >= 85


# --------------------------------------------------------------------------
# Admission (PRD 3.7)
# --------------------------------------------------------------------------
def current_care_level(admission):
    return higher(weight_term(admission["current_weight_grams"]),
                  SUPPORT_TERM.get(admission["support_modality"], "LEVEL_I"))


def developmental_bundle_score(admission):
    rounds = admission["developmental_round_count"]
    if rounds == 0:
        return q2(D0)
    kangaroo = min(D1, Decimal(admission["kangaroo_care_sessions"]) / Decimal(3)) * D100
    family = min(D1, Decimal(admission["family_presence_minutes"]) / Decimal(720)) * D100
    cluster = Decimal(admission["cluster_care_compliant_count"]) / Decimal(rounds) * D100
    light = Decimal(admission["light_cycling_compliant_count"]) / Decimal(rounds) * D100
    return q2(Decimal("0.35") * kangaroo + Decimal("0.25") * family
              + Decimal("0.20") * cluster + Decimal("0.20") * light)


def recompute_developmental(admission):
    admission["developmental_bundle_score"] = developmental_bundle_score(admission)


def recompute_milk_rollup(admission):
    total = D0
    for batch in admission_batches(admission["id"]):
        total += batch["administered_ml"]
    admission["milk_administered_ml"] = q1(total)


# --------------------------------------------------------------------------
# Milk (PRD 3.7)
# --------------------------------------------------------------------------
MILK_EXPIRY_HOURS = {"MOTHERS_OWN": 96, "DONOR_PASTEURIZED": 24}


def recompute_batch(batch):
    batch["administered_ml"] = q1(batch["administered_ml"])
    batch["discarded_ml"] = q1(batch["discarded_ml"])
    batch["remaining_ml"] = q1(batch["volume_ml"] - batch["administered_ml"]
                               - batch["discarded_ml"])
    administered = batch["administered_ml"]
    discarded = batch["discarded_ml"]
    remaining = batch["remaining_ml"]
    if discarded > 0 and remaining == 0:
        batch["status"] = "DISCARDED"
    elif batch["status"] == "QUARANTINED":
        pass
    elif remaining == 0 and administered > 0:
        batch["status"] = "ADMINISTERED"
    elif administered > 0 and remaining > 0:
        batch["status"] = "PARTIALLY_ADMINISTERED"
    elif batch["status"] in ("PARTIALLY_ADMINISTERED", "ADMINISTERED"):
        batch["status"] = "VERIFIED"


# --------------------------------------------------------------------------
# Surveillance (PRD 3.9)
# --------------------------------------------------------------------------
def birth_weight_band_weight(grams):
    if grams < 1000:
        return Decimal("1.30")
    if grams < 1500:
        return Decimal("1.15")
    if grams < 2500:
        return Decimal("1.00")
    return Decimal("0.85")


def compute_report_metrics(report):
    unit_id = report["unit_id"]
    start = report["period_start"]
    end = report["period_end"]
    admissions = [a for a in db.admissions.values() if a["unit_id"] == unit_id]
    cohort = [a for a in admissions if start <= a["created_at"] <= end]
    report["cohort_size"] = len(cohort)
    report["clabsi_count"] = len([a for a in admissions
                                  if a.get("infection_confirmed_at") is not None
                                  and start <= a["infection_confirmed_at"] <= end])
    report["mortality_count"] = len([a for a in admissions
                                     if a["care_status"] == "DECEASED"
                                     and a.get("discharged_at") is not None
                                     and start <= a["discharged_at"] <= end])
    if cohort:
        total = sum((birth_weight_band_weight(a["birth_weight_grams"]) for a in cohort),
                    D0)
        risk_weight = q4(total / Decimal(len(cohort)))
    else:
        risk_weight = q4(D1)
    report["birth_weight_risk_weight"] = risk_weight

    patient_days = report["reported_patient_days"]
    line_days = report["reported_central_line_days"]
    clabsi = Decimal(report["clabsi_count"])
    if patient_days > 0:
        report["crude_clabsi_rate"] = q2(clabsi * Decimal(1000) / Decimal(patient_days))
    else:
        report["crude_clabsi_rate"] = q2(D0)
    if line_days > 0:
        report["device_adjusted_clabsi_rate"] = q2(
            clabsi * risk_weight * Decimal(1000) / Decimal(line_days))
    else:
        report["device_adjusted_clabsi_rate"] = q2(D0)
    report["variant_applied"] = "DEVICE_ADJUSTED" if line_days > 0 else "CRUDE"
    report["data_completeness_flag"] = ("COMPLETE" if patient_days > 0 and line_days > 0
                                        else "DENOMINATOR_MISSING")
    applied = (report["device_adjusted_clabsi_rate"] if line_days > 0
               else report["crude_clabsi_rate"])
    report["network_benchmark_flag"] = ("ABOVE_BENCHMARK" if applied > Decimal("1.50")
                                        else "WITHIN_BENCHMARK")


# --------------------------------------------------------------------------
# Follow-up eligibility (PRD 3.9)
# --------------------------------------------------------------------------
def eligibility_basis(admission):
    if admission["birth_weight_grams"] < 1500:
        return "BW_UNDER_1500"
    if admission["gestational_age_weeks"] < Decimal("32.0"):
        return "GA_UNDER_32"
    referral = db.referrals.get(admission.get("referral_id"))
    diagnoses = (referral.get("diagnoses") or []) if referral else []
    if "HIE_MODERATE" in diagnoses:
        return "HIE_COOLED"
    if "SURGICAL_NEC" in diagnoses:
        return "SURGICAL_NEC"
    if admission["ventilator_days"] > 7:
        return "VENT_OVER_7D"
    return "NOT_ELIGIBLE"


def risk_tier(admission, basis=None):
    basis = basis or eligibility_basis(admission)
    if admission["birth_weight_grams"] < 1000 or basis == "HIE_COOLED":
        return "HIGH"
    return "MODERATE"


def clinic_day_bookings(clinic_unit_id, day, exclude_enrollment_id=None):
    count = 0
    for enrollment in db.enrollments.values():
        if enrollment["clinic_unit_id"] != clinic_unit_id:
            continue
        if enrollment["id"] == exclude_enrollment_id:
            continue
        if enrollment["status"] not in ("SCHEDULED", "ATTENDED"):
            continue
        confirmed = enrollment.get("confirmed_appointment_date")
        if confirmed is not None and clock.day_bucket(confirmed) == day:
            count += 1
    return count

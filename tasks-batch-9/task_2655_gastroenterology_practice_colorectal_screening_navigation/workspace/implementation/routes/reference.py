"""Plans, clinicians, patients and the logical clock."""
from flask import Blueprint

from core import db, new_record, now_iso, parse_instant, public, by_seq, fail
from core import respond_empty, respond_list, respond_object
from calcs import patient_risk_tier
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    opt_bool,
    opt_enum,
    opt_int,
    opt_number,
    pagination,
    req_date,
    req_enum,
    req_id,
    req_instant,
    req_string,
)
from services import get_patient, get_plan, get_clinician

bp = Blueprint("reference", __name__)


# ---- InsurancePlan -------------------------------------------------------
@bp.post("/insurance-plans")
def create_plan():
    auth("PracticeAdmin")
    data = body()
    plan_code = req_string(data, "plan_code", minlen=1, maxlen=32)
    payer_name = req_string(data, "payer_name")
    preventive_coverage_pct = opt_number(data, "preventive_coverage_pct", 0.00, 1.00, 1.00)
    diagnostic_coinsurance_pct = opt_number(data, "diagnostic_coinsurance_pct", 0.00, 1.00, 0.20)
    deductible_cents = opt_int(data, "deductible_cents", 0, None, 0)
    out_of_pocket_max_cents = opt_int(data, "out_of_pocket_max_cents", 0, None, 400000)
    polypectomy_carveout = opt_enum(
        data, "polypectomy_carveout", ("PREVENTIVE_RETAINED", "DIAGNOSTIC_CONVERTED"),
        "DIAGNOSTIC_CONVERTED",
    )
    modifier_33_honored = opt_bool(data, "modifier_33_honored", True)
    anesthesia_bundled = opt_bool(data, "anesthesia_bundled", False)

    for other in db.plans.values():
        if other["plan_code"] == plan_code:
            fail("ERR_DUPLICATE_IDENTIFIER", "plan_code %s already exists." % plan_code)

    plan = new_record({
        "plan_code": plan_code,
        "payer_name": payer_name,
        "preventive_coverage_pct": preventive_coverage_pct,
        "diagnostic_coinsurance_pct": diagnostic_coinsurance_pct,
        "deductible_cents": deductible_cents,
        "out_of_pocket_max_cents": out_of_pocket_max_cents,
        "polypectomy_carveout": polypectomy_carveout,
        "modifier_33_honored": modifier_33_honored,
        "anesthesia_bundled": anesthesia_bundled,
    })
    db.plans[plan["id"]] = plan
    return respond_object(plan, 201)


@bp.get("/insurance-plans/<plan_id>")
def read_plan(plan_id):
    auth("PracticeAdmin", "BillingSpecialist")
    return respond_object(get_plan(plan_id))


# ---- Clinician -----------------------------------------------------------
@bp.post("/clinicians")
def create_clinician():
    auth("PracticeAdmin")
    data = body()
    npi = req_string(data, "npi", minlen=1, maxlen=20)
    full_name = req_string(data, "full_name")
    clinician_type = req_enum(data, "clinician_type", ("ENDOSCOPIST", "ANESTHESIA"))
    max_overlapping_rooms = opt_int(data, "max_overlapping_rooms", 1, 4, 1)
    adr_benchmark_pct = opt_number(data, "adr_benchmark_pct", 0.00, 1.00, 0.25)
    credential_status = opt_enum(data, "credential_status", ("ACTIVE", "SUSPENDED"), "ACTIVE")

    for other in db.clinicians.values():
        if other["npi"] == npi:
            fail("ERR_DUPLICATE_IDENTIFIER", "npi %s already exists." % npi)

    clinician = new_record({
        "npi": npi,
        "full_name": full_name,
        "clinician_type": clinician_type,
        "max_overlapping_rooms": max_overlapping_rooms,
        "adr_benchmark_pct": adr_benchmark_pct,
        "credential_status": credential_status,
    })
    db.clinicians[clinician["id"]] = clinician
    return respond_object(clinician, 201)


@bp.get("/clinicians/<clinician_id>")
def read_clinician(clinician_id):
    auth("PracticeAdmin", "QualityOfficer", "ReferralCoordinator", "Endoscopist")
    return respond_object(get_clinician(clinician_id))


# ---- Patient -------------------------------------------------------------
@bp.post("/patients")
def create_patient():
    auth("PracticeAdmin", "ReferralCoordinator")
    data = body()
    mrn = req_string(data, "mrn", minlen=1, maxlen=32)
    birth_date = req_date(data, "birth_date")
    insurance_plan_id = req_id(data, "insurance_plan_id")
    family_history_crc = opt_bool(data, "family_history_crc", False)
    ibd_diagnosis = opt_bool(data, "ibd_diagnosis", False)
    prior_crc_history = opt_bool(data, "prior_crc_history", False)
    anticoagulant_therapy = opt_bool(data, "anticoagulant_therapy", False)
    asa_class = opt_int(data, "asa_class", 1, 5, 2)

    get_plan(insurance_plan_id)

    for other in db.patients.values():
        if other["mrn"] == mrn:
            fail("ERR_DUPLICATE_IDENTIFIER", "mrn %s already exists." % mrn)

    patient = new_record({
        "mrn": mrn,
        "birth_date": birth_date,
        "insurance_plan_id": insurance_plan_id,
        "family_history_crc": family_history_crc,
        "ibd_diagnosis": ibd_diagnosis,
        "prior_crc_history": prior_crc_history,
        "anticoagulant_therapy": anticoagulant_therapy,
        "asa_class": asa_class,
        "risk_tier": patient_risk_tier(ibd_diagnosis, prior_crc_history, family_history_crc),
        "deductible_applied_cents": 0,
        "oop_applied_cents": 0,
        "open_episode_count": 0,
        "navigation_priority": "ROUTINE",
    })
    db.patients[patient["id"]] = patient
    return respond_object(patient, 201)


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    user_id, role = auth("PracticeAdmin", "ReferralCoordinator", "PatientNavigator", "Patient")
    patient = get_patient(patient_id)
    if role == "Patient" and user_id != patient["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A Patient may read only their own record.")
    return respond_object(patient)


@bp.get("/patients")
def list_patients():
    auth("PracticeAdmin", "ReferralCoordinator", "PatientNavigator")
    limit, offset = pagination()
    insurance_plan_id = filter_value("insurance_plan_id")
    risk_tier = filter_enum("risk_tier", ("AVERAGE", "INCREASED", "HIGH"))
    navigation_priority = filter_enum("navigation_priority", ("ROUTINE", "HIGH"))
    rows = by_seq(list(db.patients.values()))
    if insurance_plan_id is not None:
        rows = [r for r in rows if r["insurance_plan_id"] == insurance_plan_id]
    if risk_tier is not None:
        rows = [r for r in rows if r["risk_tier"] == risk_tier]
    if navigation_priority is not None:
        rows = [r for r in rows if r["navigation_priority"] == navigation_priority]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


# ---- Logical clock -------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("PracticeAdmin")
    data = body()
    instant = req_instant(data, "to_iso8601")
    db.clock = instant
    return respond_empty(200)

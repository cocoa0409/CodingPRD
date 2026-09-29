"""Organisational aggregates: Unit, Patient and WocNurse (15 endpoints)."""

import re

import calc
import services
from core import (
    CE_CREDIT_FLOOR,
    ELIGIBILITY_SCORE_FLOOR,
    MAX_LOAD_BY_CERT,
    READ_ROLES,
    ROLE_DIRECTOR,
    ROLE_UNIT_CHARGE,
    D,
    F,
    apply_filters,
    authorize,
    bad_request,
    bump,
    chrono,
    fail,
    filters,
    insert,
    must,
    new_row,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    parse_input,
    public,
    public_list,
    rows_of,
    SIGNOFF_FLOOR,
)
from flask import Blueprint

bp = Blueprint("org", __name__)

POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
PATIENT_STATUSES = ("ADMITTED", "DISCHARGED")
CERT_STATUSES = ("TRAINEE", "CANDIDATE", "CERTIFIED", "LAPSED")

UNIT_CODE_RE = re.compile(r"^[A-Z0-9-]{2,12}$")


def blank_unit_ledger():
    return {
        "rental_encumbered_cents": 0,
        "rental_committed_cents": 0,
        "rental_released_cents": 0,
        "open_hapi_rca_count": 0,
        "disputed_staging_count": 0,
        "survey_posture": "OPEN",
        "last_prevalence_rate": None,
        "last_incidence_rate": None,
    }


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------
@bp.post("/units")
def create_unit():
    authorize(ROLE_DIRECTOR)
    body = parse_input([
        F("unit_code", "string", required=True, min_len=2, max_len=12),
        F("name", "string", required=True, min_len=1, max_len=120),
        F("bed_count", "int", required=True, minimum=1, maximum=400),
        F("rental_budget_cap_cents", "int", minimum=0, maximum=10 ** 12),
    ])
    if not UNIT_CODE_RE.match(body["unit_code"]):
        bad_request("unit_code must be 2-12 characters of A-Z, 0-9 or '-'.")
    for existing in rows_of("units"):
        if existing.get("unit_code") == body["unit_code"]:
            fail("ERR_DUPLICATE_NATURAL_KEY", "unit_code is already in use.")
    unit = new_row(
        "unit",
        unit_code=body["unit_code"],
        name=body["name"],
        bed_count=body["bed_count"],
        rental_budget_cap_cents=int(body.get("rental_budget_cap_cents") or 0),
        **blank_unit_ledger()
    )
    services.recompute_available(unit)
    insert("units", unit)
    return ok(public(unit), 201)


@bp.get("/units")
def list_units():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({"survey_posture": POSTURES})
    rows = chrono(apply_filters(rows_of("units"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/units/<unit_id>")
def get_unit(unit_id):
    authorize(*READ_ROLES)
    return ok(public(must("units", unit_id)))


@bp.post("/units/<unit_id>/budget-adjustments")
def adjust_budget(unit_id):
    authorize(ROLE_DIRECTOR)
    body = parse_input([
        F("delta_cents", "int", required=True, minimum=-10 ** 12, maximum=10 ** 12),
        F("reason", "string", required=True, min_len=1, max_len=2000),
    ])
    unit = must("units", unit_id)
    new_cap = int(unit.get("rental_budget_cap_cents") or 0) + int(body["delta_cents"])
    new_available = new_cap \
        - int(unit.get("rental_encumbered_cents") or 0) \
        - int(unit.get("rental_committed_cents") or 0)
    if new_cap < 0 or new_available < 0:
        fail("ERR_RENTAL_BUDGET_EXCEEDED",
             "Adjustment would drive rental headroom below zero.")
    unit["rental_budget_cap_cents"] = new_cap
    services.recompute_available(unit)
    bump(unit)
    return ok(public(unit))


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------
@bp.post("/patients")
def create_patient():
    authorize(ROLE_UNIT_CHARGE, ROLE_DIRECTOR)
    body = parse_input([
        F("mrn", "string", required=True, min_len=6, max_len=16),
        F("unit_id", "id", required=True),
        F("admitted_at", "datetime", required=True),
        F("comorbidity_count", "int", minimum=0, maximum=10),
        F("device_related_risk", "bool"),
        F("ostomy_present", "bool"),
    ])
    if body["admitted_at"] > now():
        bad_request("admitted_at must be at or before the current logical clock.")
    must("units", body["unit_id"])
    for existing in rows_of("patients"):
        if existing.get("mrn") == body["mrn"]:
            fail("ERR_DUPLICATE_NATURAL_KEY", "mrn is already in use.")
    patient = new_row(
        "pat",
        mrn=body["mrn"],
        unit_id=body["unit_id"],
        admitted_at=body["admitted_at"],
        discharged_at=None,
        status="ADMITTED",
        comorbidity_count=int(body.get("comorbidity_count") or 0),
        device_related_risk=bool(body.get("device_related_risk", False)),
        ostomy_present=bool(body.get("ostomy_present", False)),
        poa_skin_assessment_documented=False,
        pending_outpatient_followup_count=0,
    )
    insert("patients", patient)
    return ok(public(patient), 201)


@bp.get("/patients")
def list_patients():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({"unit_id": None, "status": PATIENT_STATUSES})
    rows = chrono(apply_filters(rows_of("patients"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/patients/<patient_id>")
def get_patient(patient_id):
    authorize(*READ_ROLES)
    return ok(public(must("patients", patient_id)))


@bp.post("/patients/<patient_id>/discharge")
def discharge_patient(patient_id):
    authorize(ROLE_UNIT_CHARGE, ROLE_DIRECTOR)
    body = parse_input([F("discharged_at", "datetime", required=True)])
    patient = must("patients", patient_id)
    if patient.get("status") != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED")
    for order in rows_of("support_surface_orders"):
        if order.get("patient_id") != patient_id:
            continue
        if order.get("fulfillment_status") in ("APPROVED", "DELIVERED"):
            fail("ERR_RESOURCE_NOT_ACTIVE",
                 "Patient still holds an approved or delivered support surface.")
    if body["discharged_at"] < patient.get("admitted_at"):
        bad_request("discharged_at must be at or after admitted_at.")
    patient["discharged_at"] = body["discharged_at"]
    patient["status"] = "DISCHARGED"
    bump(patient)
    return ok(public(patient))


# ---------------------------------------------------------------------------
# WocNurse
# ---------------------------------------------------------------------------
@bp.post("/woc-nurses")
def create_nurse():
    authorize(ROLE_DIRECTOR)
    body = parse_input([
        F("full_name", "string", required=True, min_len=1, max_len=120),
        F("home_unit_id", "id", required=True),
        F("ce_credits", "int", minimum=0, maximum=200),
    ])
    must("units", body["home_unit_id"])
    nurse = new_row(
        "nurse",
        full_name=body["full_name"],
        home_unit_id=body["home_unit_id"],
        certification_status="TRAINEE",
        ce_credits=int(body.get("ce_credits") or 0),
        competency_signoff_count=0,
        last_competency_signoff_at=None,
        mentored_consult_count=0,
        certification_eligibility_score=None,
        cert_expires_at=None,
        active_consult_load=0,
        max_consult_load=MAX_LOAD_BY_CERT["TRAINEE"],
    )
    insert("woc_nurses", nurse)
    return ok(public(nurse), 201)


@bp.get("/woc-nurses")
def list_nurses():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({"home_unit_id": None, "certification_status": CERT_STATUSES})
    rows = chrono(apply_filters(rows_of("woc_nurses"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/woc-nurses/<nurse_id>")
def get_nurse(nurse_id):
    authorize(*READ_ROLES)
    return ok(public(must("woc_nurses", nurse_id)))


@bp.post("/woc-nurses/<nurse_id>/competency-signoffs")
def record_signoff(nurse_id):
    authorize(ROLE_DIRECTOR)
    body = parse_input([
        F("signed_off_at", "datetime", required=True),
        F("competency_domain", "string", required=True, min_len=1, max_len=120),
    ])
    nurse = must("woc_nurses", nurse_id)
    from core import DB
    DB.competency_signoffs.append(new_row(
        "signoff",
        nurse_id=nurse_id,
        signed_off_at=body["signed_off_at"],
        competency_domain=body["competency_domain"],
    ))
    nurse["competency_signoff_count"] = int(nurse.get("competency_signoff_count") or 0) + 1
    services.recompute_last_signoff(nurse)
    services.recompute_eligibility(nurse)
    bump(nurse)
    return ok(public(nurse))


@bp.post("/woc-nurses/<nurse_id>/advance")
def advance_nurse(nurse_id):
    authorize(ROLE_DIRECTOR)
    parse_input([])
    nurse = must("woc_nurses", nurse_id)
    if nurse.get("certification_status") != "TRAINEE":
        fail("ERR_CERTIFICATION_NOT_ELIGIBLE",
             "Only a TRAINEE may be advanced to CANDIDATE.")
    if int(nurse.get("competency_signoff_count") or 0) < 1:
        fail("ERR_CERTIFICATION_NOT_ELIGIBLE",
             "At least one competency signoff is required to advance.")
    nurse["certification_status"] = "CANDIDATE"
    services.apply_max_load(nurse)
    bump(nurse)
    return ok(public(nurse))


@bp.post("/woc-nurses/<nurse_id>/certify")
def certify_nurse(nurse_id):
    authorize(ROLE_DIRECTOR)
    body = parse_input([F("cert_expires_at", "datetime", required=True)])
    nurse = must("woc_nurses", nurse_id)
    if nurse.get("certification_status") not in ("CANDIDATE", "LAPSED"):
        fail("ERR_CERTIFICATION_NOT_ELIGIBLE",
             "Only a CANDIDATE or LAPSED nurse may be certified.")
    score = nurse.get("certification_eligibility_score")
    if score is None or D(score) < ELIGIBILITY_SCORE_FLOOR:
        fail("ERR_CERTIFICATION_NOT_ELIGIBLE",
             "certification_eligibility_score is below the floor.")
    if int(nurse.get("ce_credits") or 0) < CE_CREDIT_FLOOR:
        fail("ERR_CERTIFICATION_NOT_ELIGIBLE", "ce_credits is below the floor.")
    if int(nurse.get("competency_signoff_count") or 0) < SIGNOFF_FLOOR:
        fail("ERR_CERTIFICATION_NOT_ELIGIBLE",
             "competency_signoff_count is below the floor.")
    nurse["certification_status"] = "CERTIFIED"
    nurse["cert_expires_at"] = body["cert_expires_at"]
    services.apply_max_load(nurse)
    bump(nurse)
    return ok(public(nurse))


@bp.post("/woc-nurses/<nurse_id>/lapse")
def lapse_nurse(nurse_id):
    authorize(ROLE_DIRECTOR)
    parse_input([F("reason", "string", required=True, min_len=1, max_len=2000)])
    nurse = must("woc_nurses", nurse_id)
    if nurse.get("certification_status") != "CERTIFIED":
        fail("ERR_CERTIFICATION_NOT_ELIGIBLE",
             "Only a CERTIFIED nurse may lapse.")
    nurse["certification_status"] = "LAPSED"
    services.apply_max_load(nurse)
    # active_consult_load is deliberately left alone.
    bump(nurse)
    return ok(public(nurse))

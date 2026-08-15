"""Patients, eligibility snapshots, and case opening (PRD 3.2, 3.3)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_DUPLICATE_MRN,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from services import recompute_case
from util import (
    base_record,
    get_body,
    now_iso,
    paginate,
    req_date,
    req_int,
    req_str,
    serialize,
    touch,
)

bp = Blueprint("patients", __name__)


# --- patients ---------------------------------------------------------------

@bp.post("/clearance/patients")
def create_patient():
    authenticate(["Registrar"])
    b = get_body()
    mrn = req_str(b, "mrn")
    full_name = req_str(b, "full_name")
    date_of_birth = req_date(b, "date_of_birth")
    if any(p["mrn"] == mrn for p in db.patients.values()):
        raise ApiError(ERR_DUPLICATE_MRN, "mrn already registered", 409)
    rec = base_record()
    rec.update({
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
    })
    db.patients[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/clearance/patients/<pid>")
def get_patient(pid):
    authenticate(ALL_ROLES)
    rec = db.patients.get(pid)
    if rec is None:
        raise not_found("patient not found")
    return ok_object(serialize(rec))


# --- eligibility snapshots --------------------------------------------------

@bp.post("/clearance/patients/<pid>/eligibility-snapshots")
def create_snapshot(pid):
    authenticate(["Registrar"])
    patient = db.patients.get(pid)
    if patient is None:
        raise not_found("patient not found")
    b = get_body()
    expected_patient_version = req_int(b, "expected_patient_version")
    payer_code = req_str(b, "payer_code")
    member_id = req_str(b, "member_id")
    deductible_total_cents = req_int(b, "deductible_total_cents")
    deductible_met_cents = req_int(b, "deductible_met_cents")
    oop_max_cents = req_int(b, "oop_max_cents")
    oop_met_cents = req_int(b, "oop_met_cents")
    coinsurance_pct = req_int(b, "coinsurance_pct")
    if deductible_total_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "deductible_total_cents must be >= 0", 400)
    if not (0 <= deductible_met_cents <= deductible_total_cents):
        raise ApiError(ERR_INVALID_REQUEST, "deductible_met_cents must be in 0..deductible_total_cents", 400)
    if oop_max_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "oop_max_cents must be > 0", 400)
    if not (0 <= oop_met_cents <= oop_max_cents):
        raise ApiError(ERR_INVALID_REQUEST, "oop_met_cents must be in 0..oop_max_cents", 400)
    if not (0 <= coinsurance_pct <= 100):
        raise ApiError(ERR_INVALID_REQUEST, "coinsurance_pct must be in 0..100", 400)
    # OCC on Patient.version
    if expected_patient_version != patient["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_patient_version does not match current patient version", 412)
    # supersede the prior ACTIVE snapshot for the same (patient, payer_code)
    for snap in db.snapshots.values():
        if (snap["patient_id"] == pid and snap["payer_code"] == payer_code
                and snap["status"] == "ACTIVE"):
            snap["status"] = "SUPERSEDED"
            touch(snap)
    rec = base_record()
    rec.update({
        "patient_id": pid,
        "payer_code": payer_code,
        "member_id": member_id,
        "deductible_total_cents": deductible_total_cents,
        "deductible_met_cents": deductible_met_cents,
        "oop_max_cents": oop_max_cents,
        "oop_met_cents": oop_met_cents,
        "coinsurance_pct": coinsurance_pct,
        "verified_at": now_iso(),
        "status": "ACTIVE",
    })
    db.snapshots[rec["id"]] = rec
    # snapshot capture increments Patient.version by 1
    touch(patient)
    return ok_object(serialize(rec), 201)


@bp.get("/clearance/eligibility-snapshots/<sid>")
def get_snapshot(sid):
    authenticate(ALL_ROLES)
    rec = db.snapshots.get(sid)
    if rec is None:
        raise not_found("eligibility snapshot not found")
    return ok_object(serialize(rec))


@bp.get("/clearance/eligibility-snapshots")
def list_snapshots():
    authenticate(ALL_ROLES)
    items = list(db.snapshots.values())
    patient_id = request.args.get("patient_id")
    payer_code = request.args.get("payer_code")
    status = request.args.get("status")
    if patient_id is not None:
        items = [s for s in items if s["patient_id"] == patient_id]
    if payer_code is not None:
        items = [s for s in items if s["payer_code"] == payer_code]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return ok_list([serialize(s) for s in page], meta)


# --- cases (open) -----------------------------------------------------------

@bp.post("/clearance/patients/<pid>/cases")
def create_case(pid):
    authenticate(["Registrar", "FinancialCounselor"])
    if pid not in db.patients:
        raise not_found("patient not found")
    b = get_body()
    service_date = req_date(b, "service_date")
    service_description = req_str(b, "service_description")
    rec = base_record()
    rec.update({
        "patient_id": pid,
        "service_date": service_date,
        "service_description": service_description,
        "status": "OPEN",
        "active_estimate_id": None,
        "auth_required": False,
        "auth_satisfied": True,
        "required_deposit_cents": 0,
        "deposit_posted_cents": 0,
        "deposit_satisfied": False,
        "high_dollar_flag": False,
        "escalation_cleared": True,
        "clearance_posture": "BLOCKED",
        "_first_presented_pin": None,
    })
    db.cases[rec["id"]] = rec
    recompute_case(rec)
    return ok_object(serialize(rec), 201)

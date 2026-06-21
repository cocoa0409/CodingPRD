"""Patient registration, fetch, and PDMP block clearing (PRD §3.2)."""
from flask import Blueprint, request

import db
from common import (
    get_body, require_field, opt_field, as_string, as_bool, as_int,
    as_string_array, stamp_create, touch, get_pagination, paginate,
)
from errors import err
from middleware import get_actor, require_roles
from response import object_response, array_response

bp = Blueprint("patients", __name__)

ALL_ROLES = ["PharmacyAdmin", "Pharmacist", "Technician", "Cashier"]


def serialize_patient(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"], "plan_id": p["plan_id"],
        "allergy_classes": p["allergy_classes"],
        "auto_refill_enrolled": p["auto_refill_enrolled"],
        "med_sync_day": p["med_sync_day"], "pdmp_flag": p["pdmp_flag"],
        "controlled_status": p["controlled_status"],
    }


@bp.route("/patients", methods=["POST"])
def create_patient():
    _uid, role = get_actor()
    require_roles(role, ["PharmacyAdmin", "Technician"])
    body = get_body()
    full_name = as_string(require_field(body, "full_name"), "full_name")
    dob = as_string(require_field(body, "date_of_birth"), "date_of_birth")
    plan_id = opt_field(body, "plan_id", None)
    allergy = opt_field(body, "allergy_classes", [])
    allergy = as_string_array(allergy, "allergy_classes")
    auto_refill = as_bool(opt_field(body, "auto_refill_enrolled", False), "auto_refill_enrolled")
    med_sync = opt_field(body, "med_sync_day", None)
    if med_sync is not None:
        med_sync = as_int(med_sync, "med_sync_day", 1, 28)
    with db.LOCK:
        if plan_id is not None:
            plan_id = as_string(plan_id, "plan_id")
            if plan_id not in db.insurance_plans:
                raise err("ERR_REFERENCE_NOT_FOUND", "plan_id does not reference a plan")
        patient = {
            "full_name": full_name, "date_of_birth": dob, "plan_id": plan_id,
            "allergy_classes": allergy, "auto_refill_enrolled": auto_refill,
            "med_sync_day": med_sync, "pdmp_flag": "CLEAR",
            "controlled_status": "ELIGIBLE",
        }
        stamp_create(patient)
        db.patients[patient["id"]] = patient
    return object_response(serialize_patient(patient), 201)


@bp.route("/patients", methods=["GET"])
def list_patients():
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    plan_id = request.args.get("plan_id")
    items = list(db.patients.values())
    if plan_id is not None:
        items = [p for p in items if p["plan_id"] == plan_id]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_patient(p) for p in page], limit, offset, total)


@bp.route("/patients/<rid>", methods=["GET"])
def get_patient(rid):
    _uid, role = get_actor()
    require_roles(role, ALL_ROLES)
    patient = db.patients.get(rid)
    if patient is None:
        raise err("ERR_NOT_FOUND", "Patient not found")
    return object_response(serialize_patient(patient), 200)


@bp.route("/patients/<rid>/clear-pdmp-block", methods=["POST"])
def clear_pdmp_block(rid):
    _uid, role = get_actor()
    require_roles(role, ["Pharmacist"])
    body = get_body()
    with db.LOCK:
        patient = db.patients.get(rid)
        if patient is None:
            raise err("ERR_NOT_FOUND", "Patient not found")
        if patient["pdmp_flag"] != "BLOCKED":
            raise err("ERR_PATIENT_NOT_BLOCKED", "Patient is not currently BLOCKED")
        reason = opt_field(body, "override_reason", None)
        if reason is None or (isinstance(reason, str) and reason.strip() == ""):
            raise err("ERR_OVERRIDE_REASON_REQUIRED",
                      "override_reason is required to clear a PDMP block")
        patient["pdmp_flag"] = "CLEAR"
        patient["controlled_status"] = "ELIGIBLE"
        touch(patient)
    return object_response(serialize_patient(patient), 200)

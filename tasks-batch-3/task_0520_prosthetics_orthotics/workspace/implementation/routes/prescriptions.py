"""Prescriptions (PRD §3.2)."""
from flask import Blueprint, request

from db import db, base_common_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object, ok_array
from validation import (get_json_body, require_str, require_enum, lookup,
                        parse_pagination, paginate)
from clock import is_valid_date
from services import touch
from serializers import prescription_out

bp = Blueprint("prescriptions", __name__)

DEVICE_CATEGORIES = {
    "LOWER_LIMB_PROSTHETIC", "UPPER_LIMB_PROSTHETIC",
    "SPINAL_ORTHOSIS", "LOWER_EXTREMITY_ORTHOSIS",
}


@bp.route("/op/prescriptions", methods=["POST"])
def create_prescription():
    user_id, role = get_auth()
    require_roles(role, {"Physician"})
    body = get_json_body()

    # Existence (priority 3): body FK targets must exist, validated before the
    # remaining field-well-formedness rules (priority 16).
    patient_id = require_str(body, "patient_id")
    physician_id = require_str(body, "physician_id")
    lookup(db.patients, patient_id)
    lookup(db.physicians, physician_id)

    device_category = require_enum(body, "device_category", DEVICE_CATEGORIES)
    primary_diagnosis_code = require_str(body, "primary_diagnosis_code")
    face_to_face_date = require_str(body, "face_to_face_date")
    if not is_valid_date(face_to_face_date):
        raise ApiError("ERR_INVALID_REQUEST", "face_to_face_date must be YYYY-MM-DD.")

    rx = base_common_fields()
    rx.update({
        "patient_id": patient_id,
        "physician_id": physician_id,
        "device_category": device_category,
        "primary_diagnosis_code": primary_diagnosis_code,
        "face_to_face_date": face_to_face_date,
        "status": "DRAFT",
    })
    db.prescriptions[rx["id"]] = rx
    return ok_object(prescription_out(rx), 201)


@bp.route("/op/prescriptions/<rid>", methods=["GET"])
def get_prescription(rid):
    _, role = get_auth()
    require_roles(role, {"Physician", "BillingSpecialist", "ComplianceOfficer", "Practitioner"})
    rx = lookup(db.prescriptions, rid)
    return ok_object(prescription_out(rx), 200)


@bp.route("/op/prescriptions", methods=["GET"])
def list_prescriptions():
    _, role = get_auth()
    require_roles(role, {"Physician", "BillingSpecialist", "ComplianceOfficer"})
    limit, offset = parse_pagination()

    items = list(db.prescriptions.values())
    patient_id = request.args.get("patient_id")
    physician_id = request.args.get("physician_id")
    if patient_id is not None:
        items = [r for r in items if r["patient_id"] == patient_id]
    if physician_id is not None:
        items = [r for r in items if r["physician_id"] == physician_id]

    page, total = paginate(items, limit, offset)
    return ok_array([prescription_out(r) for r in page], limit, offset, total, 200)


@bp.route("/op/prescriptions/<rid>/sign", methods=["POST"])
def sign_prescription(rid):
    user_id, role = get_auth()
    require_roles(role, {"Physician"})
    rx = lookup(db.prescriptions, rid)

    # State legality (priority 5): sign defined only from DRAFT.
    if rx["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Prescription is not in DRAFT.")
    # Precondition: acting physician owns the Rx, plus required fields present.
    if rx["physician_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Acting physician does not own this prescription.")
    if not rx["primary_diagnosis_code"] or not rx["face_to_face_date"]:
        raise ApiError("ERR_INVALID_REQUEST", "primary_diagnosis_code and face_to_face_date must be present.")

    rx["status"] = "SIGNED"
    touch(rx)
    return ok_object(prescription_out(rx), 200)


@bp.route("/op/prescriptions/<rid>/void", methods=["POST"])
def void_prescription(rid):
    user_id, role = get_auth()
    require_roles(role, {"Physician"})
    rx = lookup(db.prescriptions, rid)

    if rx["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Prescription is not in DRAFT.")
    if rx["physician_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Acting physician does not own this prescription.")

    rx["status"] = "VOIDED"
    touch(rx)
    return ok_object(prescription_out(rx), 200)

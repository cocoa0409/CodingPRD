"""Patient endpoints."""

from __future__ import annotations

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success
from errors import AppError, ERR_NOT_FOUND, ERR_FORBIDDEN
from config import ROLE_PATIENT, ROLE_ADMIN
from services.serializers import serialize
from services.occ import check_version


bp = Blueprint("patients", __name__, url_prefix="/consultation/patients")


def _patient_or_404(pid):
    row = db.find_by_id("patients", pid)
    if not row:
        raise AppError(ERR_NOT_FOUND, "Patient not found.", 404)
    return row


@bp.post("")
def create_patient():
    require_role(ROLE_ADMIN)
    body = request.get_json(silent=True) or {}
    record = {
        "full_name": body.get("full_name"),
        "date_of_birth": body.get("date_of_birth"),
        "region_code": body.get("region_code"),
        "insurance_policy_no": body.get("insurance_policy_no"),
        "insurance_status": "UNKNOWN",
        "preferred_hospital_id": body.get("preferred_hospital_id"),
        "preferred_doctor_id": body.get("preferred_doctor_id"),
        "chronic_condition_codes": body.get("chronic_condition_codes") or [],
    }
    row = db.insert("patients", record)
    return success(serialize(row), 201)


@bp.get("/<pid>")
def get_patient(pid):
    require_role(ROLE_PATIENT, ROLE_ADMIN)
    row = _patient_or_404(pid)
    # Ownership for Patient role.
    if g.role == ROLE_PATIENT and g.user_id != row["id"]:
        raise AppError(ERR_FORBIDDEN, "Patient may only access their own row.", 403)
    return success(serialize(row), 200)


@bp.patch("/<pid>")
def update_patient(pid):
    require_role(ROLE_PATIENT)
    row = _patient_or_404(pid)
    if g.user_id != row["id"]:
        raise AppError(ERR_FORBIDDEN, "Patient may only update own row.", 403)
    body = request.get_json(silent=True) or {}
    check_version(row, body)
    updates = {}
    for k in ("preferred_hospital_id", "preferred_doctor_id", "chronic_condition_codes"):
        if k in body:
            updates[k] = body[k]
    row = db.update("patients", pid, updates)
    return success(serialize(row), 200)

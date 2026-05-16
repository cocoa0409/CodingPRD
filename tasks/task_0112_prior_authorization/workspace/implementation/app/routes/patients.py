"""Patient routes."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..services.lookups import get_patient_or_404
from ..services.serialize import serialize_patient
from ..store import get_lock, get_store, stamp_create


bp = Blueprint("patients", __name__)


VALID_PLAN_TYPES = {"COMMERCIAL", "MEDICARE", "MEDICAID"}


@bp.post("/patients")
@require_auth("PlatformAdmin")
def create_patient():
    body = get_json_body()
    member_id = require_field(body, "member_id")
    full_name = require_field(body, "full_name")
    date_of_birth = require_field(body, "date_of_birth")
    plan_type = require_field(body, "plan_type")
    if plan_type not in VALID_PLAN_TYPES:
        raise APIError("ERR_VALIDATION", f"plan_type must be one of {sorted(VALID_PLAN_TYPES)}")
    if not isinstance(member_id, str) or not member_id:
        raise APIError("ERR_VALIDATION", "member_id must be a non-empty string")

    with get_lock():
        store = get_store()
        # member_id must be unique across the system.
        for existing in store.patients.values():
            if existing["member_id"] == member_id:
                raise APIError("ERR_VALIDATION", "member_id already exists")
        rec = {
            "member_id": member_id,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "plan_type": plan_type,
            "status": "ACTIVE",
        }
        stamp_create(rec)
        store.patients[rec["id"]] = rec

    body_out, status = success_response(serialize_patient(rec), status=201)
    return jsonify(body_out), status


@bp.get("/patients/<patient_id>")
@require_auth("PlatformAdmin", "Provider", "InitialReviewer", "MedicalDirector", "ExternalReviewer")
def get_patient(patient_id: str):
    rec = get_patient_or_404(patient_id)
    body_out, status = success_response(serialize_patient(rec))
    return jsonify(body_out), status

"""Patient endpoints — PRD §3.1."""
from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..errors import APIError
from ..helpers import (
    get_json_body,
    get_pagination_params,
    paginate,
    require_field,
)
from ..responses import list_response, success_response
from ..services.lookups import get_clinic, get_patient
from ..services.serialize import serialize_patient
from ..store import get_lock, get_store, stamp_create


bp = Blueprint("patients", __name__)


@bp.post("/patients")
@require_auth("ClinicAdmin", "BCBA")
def create_patient():
    body = get_json_body()
    clinic_id = require_field(body, "clinic_id")
    legal_name = require_field(body, "legal_name")
    date_of_birth = require_field(body, "date_of_birth")
    insurance_member_id = require_field(body, "insurance_member_id")
    if not isinstance(legal_name, str) or not legal_name.strip():
        raise APIError("ERR_VALIDATION", "legal_name must be a non-empty string")
    if not isinstance(date_of_birth, str):
        raise APIError("ERR_VALIDATION", "date_of_birth must be a string")
    if not isinstance(insurance_member_id, str) or not insurance_member_id.strip():
        raise APIError("ERR_VALIDATION", "insurance_member_id must be a non-empty string")

    with get_lock():
        clinic = get_clinic(clinic_id)  # ERR_NOT_FOUND if absent
        record = stamp_create(
            {
                "clinic_id": clinic_id,
                "legal_name": legal_name,
                "date_of_birth": date_of_birth,
                "insurance_member_id": insurance_member_id,
                "clinical_progress_score_provisional": 0.0,
                "clinical_progress_score_adjudicated": 0.0,
                "status": "ACTIVE",
            },
            now=clinic["now_ts"],
        )
        get_store().patients[record["id"]] = record

    body_out, status = success_response(serialize_patient(record), status=201)
    return jsonify(body_out), status


@bp.get("/patients")
@require_auth("ClinicAdmin", "BCBA", "RBT")
def list_patients():
    limit, offset = get_pagination_params()
    status_filter = request.args.get("status")
    with get_lock():
        items = [p for p in get_store().patients.values()
                 if status_filter is None or p["status"] == status_filter]
        items.sort(key=lambda p: p["created_at"])
        page, total = paginate(items, limit, offset)
        body_out, status = list_response(
            [serialize_patient(p) for p in page], total, limit, offset
        )
    return jsonify(body_out), status


@bp.get("/patients/<patient_id>")
@require_auth("ClinicAdmin", "BCBA", "RBT", "PayerAdmin")
def read_patient(patient_id):
    with get_lock():
        p = get_patient(patient_id)
    body_out, status = success_response(serialize_patient(p))
    return jsonify(body_out), status

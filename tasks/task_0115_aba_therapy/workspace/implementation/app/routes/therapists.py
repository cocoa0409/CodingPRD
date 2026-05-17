"""Therapist endpoints — PRD §3.1."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..services.lookups import get_clinic, get_therapist
from ..services.serialize import serialize_therapist
from ..store import get_lock, get_store, stamp_create


bp = Blueprint("therapists", __name__)


VALID_CREDENTIALS = {"BCBA", "RBT"}


@bp.post("/therapists")
@require_auth("ClinicAdmin")
def create_therapist():
    body = get_json_body()
    clinic_id = require_field(body, "clinic_id")
    legal_name = require_field(body, "legal_name")
    credential = require_field(body, "credential")
    license_number = require_field(body, "license_number")

    if credential not in VALID_CREDENTIALS:
        raise APIError("ERR_VALIDATION", "credential must be BCBA or RBT")
    if not isinstance(legal_name, str) or not legal_name.strip():
        raise APIError("ERR_VALIDATION", "legal_name must be a non-empty string")
    if not isinstance(license_number, str) or not license_number.strip():
        raise APIError("ERR_VALIDATION", "license_number must be a non-empty string")

    with get_lock():
        clinic = get_clinic(clinic_id)
        record = stamp_create(
            {
                "clinic_id": clinic_id,
                "legal_name": legal_name,
                "credential": credential,
                "license_number": license_number,
                "status": "ACTIVE",
            },
            now=clinic["now_ts"],
        )
        get_store().therapists[record["id"]] = record

    body_out, status = success_response(serialize_therapist(record), status=201)
    return jsonify(body_out), status


@bp.get("/therapists/<therapist_id>")
@require_auth("ClinicAdmin", "BCBA", "RBT", "PayerAdmin")
def read_therapist(therapist_id):
    with get_lock():
        t = get_therapist(therapist_id)
    body_out, status = success_response(serialize_therapist(t))
    return jsonify(body_out), status

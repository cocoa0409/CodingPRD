"""Clinic endpoints — PRD §3.1."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import DETERMINISTIC_EPOCH
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..services.lookups import get_clinic
from ..services.serialize import serialize_clinic
from ..store import get_lock, get_store, stamp_create


bp = Blueprint("clinics", __name__)


@bp.post("/clinics")
@require_auth("ClinicAdmin")
def create_clinic():
    body = get_json_body()
    name = require_field(body, "name")
    if not isinstance(name, str) or not name.strip():
        raise APIError("ERR_VALIDATION", "name must be a non-empty string")

    with get_lock():
        record = stamp_create(
            {"name": name, "now_ts": DETERMINISTIC_EPOCH},
            now=DETERMINISTIC_EPOCH,
        )
        get_store().clinics[record["id"]] = record

    body_out, status = success_response(serialize_clinic(record), status=201)
    return jsonify(body_out), status


@bp.get("/clinics/<clinic_id>")
@require_auth("BCBA", "RBT", "ClinicAdmin", "PayerAdmin")
def read_clinic(clinic_id):
    with get_lock():
        clinic = get_clinic(clinic_id)
    body_out, status = success_response(serialize_clinic(clinic))
    return jsonify(body_out), status

"""Patient routes — SCAFFOLD §1.5 / PRD §3.1."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..helpers import (
    check_version,
    get_json_body,
    get_pagination_params,
    optional_field,
    require_field,
)
from ..responses import list_response, success_response
from ..services.lookups import lookup_wage_index
from ..services.serialize import patient_view
from ..store import get_lock, get_store, new_id, real_now_iso, stamp_create, stamp_update


bp = Blueprint("patients", __name__)


def _validate_zip(value) -> str:
    if not isinstance(value, str) or len(value) != 5 or not value.isdigit():
        raise APIError("ERR_VALIDATION", "home_zip must be a 5-digit string")
    return value


def _validate_medicare_id(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise APIError("ERR_VALIDATION", "medicare_id must be a non-empty string")
    return value


def _find_patient(patient_id: str) -> dict:
    store = get_store()
    p = store.patients.get(patient_id)
    if p is None:
        raise APIError("ERR_NOT_FOUND", f"Patient {patient_id} not found")
    return p


@bp.post("/patients")
@require_auth("IntakeCoordinator", "PlatformAdmin")
def create_patient():
    body = get_json_body()
    full_name = require_field(body, "full_name")
    medicare_id = _validate_medicare_id(require_field(body, "medicare_id"))
    home_zip = _validate_zip(require_field(body, "home_zip"))
    if not isinstance(full_name, str) or not full_name.strip():
        raise APIError("ERR_VALIDATION", "full_name must be a non-empty string")

    with get_lock():
        store = get_store()
        # Medicare ID uniqueness.
        for existing in store.patients.values():
            if existing["medicare_id"] == medicare_id:
                raise APIError("ERR_VALIDATION", "medicare_id must be unique")

        record = {
            "id": new_id(),
            "full_name": full_name,
            "medicare_id": medicare_id,
            "home_zip": home_zip,
            "wage_index": lookup_wage_index(home_zip),
        }
        stamp_create(record)
        store.patients[record["id"]] = record

        body_out, status = success_response(patient_view(record), status=201)
    return jsonify(body_out), status


@bp.get("/patients/<patient_id>")
@require_auth("IntakeCoordinator", "FieldClinician", "BillingSpecialist", "PlatformAdmin")
def get_patient(patient_id: str):
    p = _find_patient(patient_id)
    body, status = success_response(patient_view(p))
    return jsonify(body), status


@bp.get("/patients")
@require_auth("IntakeCoordinator", "BillingSpecialist", "PlatformAdmin")
def list_patients():
    from flask import request

    limit, offset = get_pagination_params()
    medicare_filter = request.args.get("medicare_id")

    store = get_store()
    items = list(store.patients.values())
    if medicare_filter is not None:
        items = [p for p in items if p["medicare_id"] == medicare_filter]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    body, status = list_response([patient_view(p) for p in page], total, limit, offset)
    return jsonify(body), status


@bp.patch("/patients/<patient_id>")
@require_auth("IntakeCoordinator", "PlatformAdmin")
def patch_patient(patient_id: str):
    body = get_json_body()
    with get_lock():
        p = _find_patient(patient_id)
        check_version(p, optional_field(body, "version"))

        if "full_name" in body and body["full_name"] is not None:
            fn = body["full_name"]
            if not isinstance(fn, str) or not fn.strip():
                raise APIError("ERR_VALIDATION", "full_name must be a non-empty string")
            p["full_name"] = fn

        if "home_zip" in body and body["home_zip"] is not None:
            zip_value = _validate_zip(body["home_zip"])
            if zip_value != p["home_zip"]:
                p["home_zip"] = zip_value
                p["wage_index"] = lookup_wage_index(zip_value)

        stamp_update(p)
        body_out, status = success_response(patient_view(p))
    return jsonify(body_out), status

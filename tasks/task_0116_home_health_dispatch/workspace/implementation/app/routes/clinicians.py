"""Clinician routes — SCAFFOLD §1.5 / PRD §3.2."""
from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..clock import parse_date
from ..errors import APIError
from ..helpers import (
    check_version,
    get_json_body,
    get_pagination_params,
    optional_field,
    require_field,
)
from ..responses import list_response, success_response
from ..services.serialize import clinician_view
from ..store import get_lock, get_store, new_id, stamp_create, stamp_update


bp = Blueprint("clinicians", __name__)


VALID_DISCIPLINES = {"SN", "PT", "OT", "SLP", "HHA"}
VALID_STATUSES = {"AVAILABLE", "SUSPENDED"}


def _validate_discipline(value) -> str:
    if value not in VALID_DISCIPLINES:
        raise APIError(
            "ERR_VALIDATION",
            f"discipline must be one of {sorted(VALID_DISCIPLINES)}",
        )
    return value


def _validate_iso_date(value, field: str) -> str:
    parse_date(value)
    return value


def _find_clinician(clinician_id: str) -> dict:
    store = get_store()
    c = store.clinicians.get(clinician_id)
    if c is None:
        raise APIError("ERR_NOT_FOUND", f"Clinician {clinician_id} not found")
    return c


@bp.post("/clinicians")
@require_auth("PlatformAdmin")
def create_clinician():
    body = get_json_body()
    full_name = require_field(body, "full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        raise APIError("ERR_VALIDATION", "full_name must be a non-empty string")
    discipline = _validate_discipline(require_field(body, "discipline"))
    license_expiration_date = _validate_iso_date(
        require_field(body, "license_expiration_date"), "license_expiration_date"
    )

    with get_lock():
        record = {
            "id": new_id(),
            "full_name": full_name,
            "discipline": discipline,
            "license_expiration_date": license_expiration_date,
            "status": "AVAILABLE",
        }
        stamp_create(record)
        get_store().clinicians[record["id"]] = record

        body_out, status = success_response(clinician_view(record), status=201)
    return jsonify(body_out), status


@bp.get("/clinicians/<clinician_id>")
@require_auth("PlatformAdmin", "IntakeCoordinator", "FieldClinician")
def get_clinician(clinician_id: str):
    c = _find_clinician(clinician_id)
    body, status = success_response(clinician_view(c))
    return jsonify(body), status


@bp.patch("/clinicians/<clinician_id>")
@require_auth("PlatformAdmin")
def patch_clinician(clinician_id: str):
    body = get_json_body()
    with get_lock():
        c = _find_clinician(clinician_id)
        check_version(c, optional_field(body, "version"))

        if "status" in body and body["status"] is not None:
            new_status = body["status"]
            if new_status not in VALID_STATUSES:
                raise APIError(
                    "ERR_VALIDATION",
                    f"status must be one of {sorted(VALID_STATUSES)}",
                )
            c["status"] = new_status

        if "license_expiration_date" in body and body["license_expiration_date"] is not None:
            d = _validate_iso_date(body["license_expiration_date"], "license_expiration_date")
            c["license_expiration_date"] = d

        stamp_update(c)
        body_out, status = success_response(clinician_view(c))
    return jsonify(body_out), status


@bp.get("/clinicians")
@require_auth("IntakeCoordinator", "PlatformAdmin")
def list_clinicians():
    limit, offset = get_pagination_params()
    discipline_filter = request.args.get("discipline")
    status_filter = request.args.get("status")
    if discipline_filter is not None and discipline_filter not in VALID_DISCIPLINES:
        raise APIError(
            "ERR_VALIDATION",
            f"discipline must be one of {sorted(VALID_DISCIPLINES)}",
        )
    if status_filter is not None and status_filter not in VALID_STATUSES:
        raise APIError(
            "ERR_VALIDATION",
            f"status must be one of {sorted(VALID_STATUSES)}",
        )

    items = list(get_store().clinicians.values())
    if discipline_filter is not None:
        items = [c for c in items if c["discipline"] == discipline_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    body, status = list_response([clinician_view(c) for c in page], total, limit, offset)
    return jsonify(body), status

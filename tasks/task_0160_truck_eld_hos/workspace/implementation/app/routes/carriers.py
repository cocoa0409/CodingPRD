"""/carriers endpoints."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import ApiError, ERR_INVALID_INPUT, ERR_NOT_FOUND
from ..serializers import serialize_carrier
from ..store import store
from ..util import require_json_body, require_str, validate_dot_number


carriers_bp = Blueprint("carriers", __name__)


@carriers_bp.post("/carriers")
@require_auth({"PlatformAdmin"})
def create_carrier():
    payload = require_json_body()
    dot_number = require_str(payload, "dot_number", max_len=32)
    validate_dot_number(dot_number)
    legal_name = require_str(payload, "legal_name", max_len=256)
    safety_contact_user_id = require_str(payload, "safety_contact_user_id", max_len=256)

    with store.lock:
        for c in store.carriers.values():
            if c["dot_number"] == dot_number:
                raise ApiError(ERR_INVALID_INPUT, 400, "dot_number must be unique.")
        entity = {
            "dot_number": dot_number,
            "legal_name": legal_name,
            "safety_contact_user_id": safety_contact_user_id,
        }
        store.stamp_create(entity)
        store.carriers[entity["id"]] = entity
    return ok_object(serialize_carrier(entity), status=201)


@carriers_bp.get("/carriers/<carrier_id>")
@require_auth({"PlatformAdmin", "CarrierSafetyOfficer", "FMCSAAuditor"})
def get_carrier(carrier_id: str):
    c = store.carriers.get(carrier_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Carrier not found.")
    return ok_object(serialize_carrier(c))

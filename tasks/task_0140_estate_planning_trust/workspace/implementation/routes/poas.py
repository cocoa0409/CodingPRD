"""PowerOfAttorney endpoints (SCAFFOLD §1.5 poas)."""
from __future__ import annotations

from flask import Blueprint, request

from config import ASSET_CLASSES, POA_TYPES, POA_STATUSES
from db import store
from errors import ApiError
from middleware import require_auth
from response import success
from services.common import (
    bump,
    check_version,
    get_json_body,
    require_child,
    require_estate,
)
from services.serializers import serialize_poa
from utils import new_uuid, parse_iso_datetime


bp = Blueprint("poas", __name__)


def _validate_scope(scope) -> list:
    """asset_class_scope: array of valid asset_class literals OR 'ALL' sentinel
    OR ['ALL']. We normalize to a Python list; the literal 'ALL' is permitted
    either as a bare string (PRD says "the value ALL is also accepted") or as
    a list containing 'ALL'.
    """
    if scope == "ALL":
        return ["ALL"]
    if not isinstance(scope, list):
        raise ApiError("ERR_BAD_REQUEST", 400, "asset_class_scope must be an array.")
    valid = set(ASSET_CLASSES) | {"ALL"}
    for item in scope:
        if item not in valid:
            raise ApiError("ERR_BAD_REQUEST", 400,
                           f"asset_class_scope contains invalid value: {item}")
    return list(scope)


@bp.post("/estates/<estate_id>/poas")
@require_auth(["Executor"])
def create_poa(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        require_estate(estate_id)
        poa_type = body.get("poa_type")
        if poa_type not in POA_TYPES:
            raise ApiError("ERR_BAD_REQUEST", 400, "poa_type must be one of the enum literals.")
        agent_id = body.get("agent_fiduciary_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ApiError("ERR_BAD_REQUEST", 400, "agent_fiduciary_id is required.")
        # FK validate.
        agent = store.fiduciaries.get(agent_id)
        if not agent or agent["estate_id"] != estate_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "agent_fiduciary_id does not reference a fiduciary in this estate.")
        scope = body.get("asset_class_scope")
        scope = _validate_scope(scope) if scope is not None else []
        eff_raw = body.get("effective_at")
        if not eff_raw:
            raise ApiError("ERR_BAD_REQUEST", 400, "effective_at is required.")
        eff = parse_iso_datetime(eff_raw)
        if eff is None:
            raise ApiError("ERR_BAD_REQUEST", 400, "effective_at must be ISO 8601 UTC.")

        pid = new_uuid()
        now = store.now()
        p = {
            "id": pid,
            "estate_id": estate_id,
            "poa_type": poa_type,
            "agent_fiduciary_id": agent_id,
            "asset_class_scope": scope,
            "effective_at": eff,
            "revoked_at": None,
            "status": "PENDING",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.poas[pid] = p
    return success(serialize_poa(p), 201)


@bp.get("/estates/<estate_id>/poas/<poa_id>")
@require_auth(["Executor", "CourtClerk"])
def get_poa(estate_id: str, poa_id: str):
    with store.lock:
        require_estate(estate_id)
        p = require_child(store.poas, estate_id, poa_id)
    return success(serialize_poa(p), 200)


@bp.post("/estates/<estate_id>/poas/<poa_id>/state")
@require_auth(["Executor"])
def transition_poa_state(estate_id: str, poa_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in POA_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409, "Unknown target status for POA transition.")
    if to_status != "REVOKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only REVOKED transition is supported via this endpoint.")
    with store.lock:
        require_estate(estate_id)
        p = require_child(store.poas, estate_id, poa_id)
        check_version(p, body)
        if p["status"] not in ("PENDING", "ACTIVE"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           f"Cannot revoke a POA in status {p['status']}.")
        p["status"] = "REVOKED"
        p["revoked_at"] = store.now()
        bump(p)
    return success(serialize_poa(p), 200)

"""HIPAAAuthorization endpoints (SCAFFOLD §1.5 hipaa)."""
from __future__ import annotations

from flask import Blueprint, request

from config import HIPAA_SCOPES, HIPAA_STATUSES
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
from services.serializers import serialize_hipaa
from utils import new_uuid, parse_iso_datetime


bp = Blueprint("hipaa", __name__)


@bp.post("/estates/<estate_id>/hipaa")
@require_auth(["Executor"])
def create_hipaa(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        require_estate(estate_id)
        recipient = body.get("authorized_recipient")
        if not isinstance(recipient, str) or not recipient.strip():
            raise ApiError("ERR_BAD_REQUEST", 400, "authorized_recipient is required.")
        scope = body.get("scope")
        if scope not in HIPAA_SCOPES:
            raise ApiError("ERR_BAD_REQUEST", 400, "scope must be one of the enum literals.")
        signed_raw = body.get("signed_at")
        if not signed_raw:
            raise ApiError("ERR_BAD_REQUEST", 400, "signed_at is required.")
        signed = parse_iso_datetime(signed_raw)
        if signed is None:
            raise ApiError("ERR_BAD_REQUEST", 400, "signed_at must be ISO 8601 UTC.")
        expires = None
        if body.get("expires_at") is not None:
            expires = parse_iso_datetime(body.get("expires_at"))
            if expires is None:
                raise ApiError("ERR_BAD_REQUEST", 400, "expires_at must be ISO 8601 UTC.")

        hid = new_uuid()
        now = store.now()
        h = {
            "id": hid,
            "estate_id": estate_id,
            "authorized_recipient": recipient,
            "scope": scope,
            "signed_at": signed,
            "expires_at": expires,
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.hipaa_auths[hid] = h
    return success(serialize_hipaa(h), 201)


@bp.get("/estates/<estate_id>/hipaa/<hipaa_id>")
@require_auth(["Executor", "CourtClerk"])
def get_hipaa(estate_id: str, hipaa_id: str):
    with store.lock:
        require_estate(estate_id)
        h = require_child(store.hipaa_auths, estate_id, hipaa_id)
    return success(serialize_hipaa(h), 200)


@bp.post("/estates/<estate_id>/hipaa/<hipaa_id>/state")
@require_auth(["Executor"])
def transition_hipaa_state(estate_id: str, hipaa_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in HIPAA_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409, "Unknown target status for HIPAA transition.")
    if to_status != "REVOKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only REVOKED transition is supported via this endpoint.")
    with store.lock:
        require_estate(estate_id)
        h = require_child(store.hipaa_auths, estate_id, hipaa_id)
        check_version(h, body)
        if h["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409,
                           f"Cannot revoke a HIPAA authorization in status {h['status']}.")
        h["status"] = "REVOKED"
        bump(h)
    return success(serialize_hipaa(h), 200)

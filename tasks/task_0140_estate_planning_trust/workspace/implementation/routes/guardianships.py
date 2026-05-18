"""GuardianshipDirective endpoints (SCAFFOLD §1.5 guardianships)."""
from __future__ import annotations

from flask import Blueprint, request

from config import GUARDIANSHIP_STATUSES
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
from services.serializers import serialize_guardianship
from utils import new_uuid, parse_iso_datetime


bp = Blueprint("guardianships", __name__)


@bp.post("/estates/<estate_id>/guardianships")
@require_auth(["Executor"])
def create_guardianship(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        require_estate(estate_id)
        minor_id = body.get("minor_beneficiary_id")
        guardian_id = body.get("guardian_fiduciary_id")
        eff_raw = body.get("effective_at")
        if not isinstance(minor_id, str) or not minor_id:
            raise ApiError("ERR_BAD_REQUEST", 400, "minor_beneficiary_id is required.")
        if not isinstance(guardian_id, str) or not guardian_id:
            raise ApiError("ERR_BAD_REQUEST", 400, "guardian_fiduciary_id is required.")
        if not eff_raw:
            raise ApiError("ERR_BAD_REQUEST", 400, "effective_at is required.")
        eff = parse_iso_datetime(eff_raw)
        if eff is None:
            raise ApiError("ERR_BAD_REQUEST", 400, "effective_at must be ISO 8601 UTC.")

        minor = store.beneficiaries.get(minor_id)
        if not minor or minor["estate_id"] != estate_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "minor_beneficiary_id does not reference a beneficiary in this estate.")
        if not minor.get("is_minor"):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "Referenced beneficiary is not a minor.")

        guardian = store.fiduciaries.get(guardian_id)
        if not guardian or guardian["estate_id"] != estate_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "guardian_fiduciary_id does not reference a fiduciary in this estate.")
        if guardian["scope_type"] != "GUARDIAN":
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "Referenced fiduciary is not a GUARDIAN.")

        # effective_at must not be in the past (priority 14).
        now = store.logical_now()
        if eff < now:
            raise ApiError("ERR_DIRECTIVE_EFFECTIVE_PAST", 422,
                           "effective_at must be at or after the current logical clock.")

        gid = new_uuid()
        now_stamp = store.now()
        g = {
            "id": gid,
            "estate_id": estate_id,
            "minor_beneficiary_id": minor_id,
            "guardian_fiduciary_id": guardian_id,
            "effective_at": eff,
            "status": "DRAFT",
            "created_at": now_stamp,
            "updated_at": now_stamp,
            "version": 1,
        }
        store.guardianships[gid] = g

        # Per PRD §3.1: if a prior directive for the same minor is EFFECTIVE,
        # it auto-supersedes when this new directive's auto-transition fires
        # later. The supersede happens in clock_engine.sweep when this DRAFT
        # becomes EFFECTIVE.
    return success(serialize_guardianship(g), 201)


@bp.get("/estates/<estate_id>/guardianships/<guardianship_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def get_guardianship(estate_id: str, guardianship_id: str):
    with store.lock:
        require_estate(estate_id)
        g = require_child(store.guardianships, estate_id, guardianship_id)
    return success(serialize_guardianship(g), 200)


@bp.post("/estates/<estate_id>/guardianships/<guardianship_id>/state")
@require_auth(["CourtClerk"])
def transition_guardianship_state(estate_id: str, guardianship_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in GUARDIANSHIP_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409, "Unknown target status for guardianship transition.")
    if to_status != "REVOKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "CourtClerk-driven guardianship transition must be REVOKED.")

    with store.lock:
        estate = require_estate(estate_id)
        g = require_child(store.guardianships, estate_id, guardianship_id)
        check_version(g, body)
        current = g["status"]
        if current not in ("DRAFT", "EFFECTIVE"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           f"Cannot revoke a guardianship in status {current}.")
        if current == "EFFECTIVE" and estate["admin_phase"] == "DISTRIBUTING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot revoke an EFFECTIVE guardianship while estate is DISTRIBUTING.")
        was_effective = (current == "EFFECTIVE")
        minor_id = g["minor_beneficiary_id"]
        g["status"] = "REVOKED"
        bump(g)
        if was_effective:
            minor = store.beneficiaries.get(minor_id)
            if minor and minor.get("guardianship_id") == g["id"]:
                minor["guardianship_id"] = None
                bump(minor)
    return success(serialize_guardianship(g), 200)

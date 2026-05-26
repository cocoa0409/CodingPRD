"""MeetAndGreet routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SITTER_NOT_CLEARED,
)
from middleware import require_auth
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    optional_str,
    paginate,
    parse_pagination,
    require_iso8601,
    require_str,
    sorted_by_created_at,
)
from services.lookup import (
    bg_check_for_sitter,
    fk_owner,
    fk_pet,
    fk_sitter,
    get_meet_and_greet_or_404,
)

bp = Blueprint("meet_and_greets", __name__)


_MG_STATUSES = {
    "SCHEDULED",
    "COMPLETED_APPROVED",
    "COMPLETED_DECLINED",
    "NO_SHOW",
    "CANCELLED",
}


def mg_to_dict(m: dict) -> dict:
    return {
        "id": m["id"],
        "owner_id": m["owner_id"],
        "sitter_id": m["sitter_id"],
        "pet_id": m["pet_id"],
        "scheduled_at": m["scheduled_at"],
        "status": m["status"],
        "decided_at": m["decided_at"],
        "notes": m["notes"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.post("/api/v1/meet-and-greets")
@require_auth(roles=["Owner"])
def create_mg():
    body = get_json_body()
    owner_id = require_str(body, "owner_id")
    sitter_id = require_str(body, "sitter_id")
    pet_id = require_str(body, "pet_id")
    scheduled_at_dt = require_iso8601(body, "scheduled_at")
    notes = optional_str(body, "notes", "")

    # FK validations
    fk_owner(owner_id)
    sitter = fk_sitter(sitter_id)
    fk_pet(pet_id)

    # Sitter must have CLEARED BackgroundCheck at MeetAndGreet creation
    bc = bg_check_for_sitter(sitter_id)
    if bc is None or bc["status"] != "CLEARED":
        raise ApiError(
            ERR_SITTER_NOT_CLEARED,
            "Sitter does not have a CLEARED BackgroundCheck.",
        )

    with db.lock:
        mg = {
            **new_common_fields(),
            "owner_id": owner_id,
            "sitter_id": sitter_id,
            "pet_id": pet_id,
            "scheduled_at": db.fmt_ts(scheduled_at_dt),
            "status": "SCHEDULED",
            "decided_at": None,
            "notes": notes,
        }
        db.meet_and_greets[mg["id"]] = mg
    return response.ok(mg_to_dict(mg), status=201)


@bp.get("/api/v1/meet-and-greets/<mid>")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin"])
def get_mg(mid: str):
    m = get_meet_and_greet_or_404(mid)
    return response.ok(mg_to_dict(m))


@bp.get("/api/v1/meet-and-greets")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin"])
def list_mg():
    limit, offset = parse_pagination()
    owner_id = request.args.get("owner_id")
    sitter_id = request.args.get("sitter_id")
    pet_id = request.args.get("pet_id")
    status_filter = request.args.get("status")

    items = list(db.meet_and_greets.values())
    if owner_id is not None:
        items = [m for m in items if m["owner_id"] == owner_id]
    if sitter_id is not None:
        items = [m for m in items if m["sitter_id"] == sitter_id]
    if pet_id is not None:
        items = [m for m in items if m["pet_id"] == pet_id]
    if status_filter is not None:
        if status_filter not in _MG_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, f"Invalid status filter: {status_filter}")
        items = [m for m in items if m["status"] == status_filter]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([mg_to_dict(m) for m in page], limit, offset, total)


def _decide_mg(mid: str, *, new_status: str, allow_notes: bool,
               require_time_gate: bool = False,
               require_sitter_active: bool = False,
               no_show_60min: bool = False):
    m = get_meet_and_greet_or_404(mid)
    if m["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "MeetAndGreet must be SCHEDULED.")
    body = get_json_body()

    if require_time_gate:
        # scheduled_at <= system_clock
        scheduled_dt = db.parse_ts(m["scheduled_at"])
        if db.utcnow() < scheduled_dt:
            raise ApiError(
                ERR_INVALID_STATE,
                "Cannot approve before scheduled_at.",
            )
    if no_show_60min:
        scheduled_dt = db.parse_ts(m["scheduled_at"])
        if db.utcnow() < scheduled_dt + timedelta(minutes=60):
            raise ApiError(
                ERR_INVALID_STATE,
                "Cannot mark no-show within 60 minutes of scheduled_at.",
            )
    if require_sitter_active:
        sitter = db.sitters.get(m["sitter_id"])
        if sitter is None or sitter["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Sitter must be ACTIVE.")

    with db.lock:
        m["status"] = new_status
        m["decided_at"] = db.fmt_ts(db.utcnow())
        if allow_notes and "notes" in body and body["notes"] is not None:
            if not isinstance(body["notes"], str):
                raise ApiError(ERR_INVALID_REQUEST, "notes must be a string.")
            m["notes"] = body["notes"]
        bump(m)
    return response.ok(mg_to_dict(m))


@bp.post("/api/v1/meet-and-greets/<mid>/approve")
@require_auth(roles=["Owner"])
def approve_mg(mid: str):
    return _decide_mg(
        mid,
        new_status="COMPLETED_APPROVED",
        allow_notes=True,
        require_time_gate=True,
        require_sitter_active=True,
    )


@bp.post("/api/v1/meet-and-greets/<mid>/decline")
@require_auth(roles=["Owner"])
def decline_mg(mid: str):
    return _decide_mg(mid, new_status="COMPLETED_DECLINED", allow_notes=True)


@bp.post("/api/v1/meet-and-greets/<mid>/mark-no-show")
@require_auth(roles=["PlatformAdmin"])
def mark_no_show_mg(mid: str):
    return _decide_mg(
        mid,
        new_status="NO_SHOW",
        allow_notes=True,
        no_show_60min=True,
    )


@bp.post("/api/v1/meet-and-greets/<mid>/cancel")
@require_auth(roles=["Owner"])
def cancel_mg(mid: str):
    return _decide_mg(mid, new_status="CANCELLED", allow_notes=True)

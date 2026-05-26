"""BackgroundCheck routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_BG_CHECK_EXISTS,
)
from middleware import require_auth
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_enum,
    require_str,
    sorted_by_created_at,
)
from services.lookup import (
    fk_sitter,
    get_background_check_or_404,
    bg_check_for_sitter,
)
from services.sitter_logic import cascade1_bg_check_flagged

bp = Blueprint("background_checks", __name__)


_BG_PROVIDERS = {"CHECKR", "ACCURATE", "FIRST_ADVANTAGE"}
_BG_STATUSES = {"PENDING", "CLEARED", "FLAGGED"}


def bg_to_dict(b: dict) -> dict:
    return {
        "id": b["id"],
        "sitter_id": b["sitter_id"],
        "provider": b["provider"],
        "status": b["status"],
        "cleared_at": b["cleared_at"],
        "flagged_reason": b["flagged_reason"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.post("/api/v1/background-checks")
@require_auth(roles=["PlatformAdmin"])
def create_bg_check():
    body = get_json_body()
    sitter_id = require_str(body, "sitter_id")
    provider = require_enum(body, "provider", _BG_PROVIDERS)

    sitter = fk_sitter(sitter_id)

    # State: Sitter.status must be APPLIED
    if sitter["status"] != "APPLIED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Sitter must be APPLIED to create a BackgroundCheck.",
        )
    # Uniqueness
    if bg_check_for_sitter(sitter_id) is not None:
        raise ApiError(ERR_BG_CHECK_EXISTS, "A BackgroundCheck already exists for this Sitter.")

    with db.lock:
        bc = {
            **new_common_fields(),
            "sitter_id": sitter_id,
            "provider": provider,
            "status": "PENDING",
            "cleared_at": None,
            "flagged_reason": None,
        }
        db.background_checks[bc["id"]] = bc

        # Side effect: advance sitter to BG_CHECK_PENDING
        sitter["status"] = "BG_CHECK_PENDING"
        bump(sitter)

    return response.ok(bg_to_dict(bc), status=201)


@bp.get("/api/v1/background-checks/<bid>")
@require_auth(roles=["PlatformAdmin", "ClaimsAdjuster"])
def get_bg(bid: str):
    b = get_background_check_or_404(bid)
    return response.ok(bg_to_dict(b))


@bp.get("/api/v1/background-checks")
@require_auth(roles=["PlatformAdmin", "ClaimsAdjuster"])
def list_bg():
    limit, offset = parse_pagination()
    sitter_id = request.args.get("sitter_id")
    status_filter = request.args.get("status")

    items = list(db.background_checks.values())
    if sitter_id is not None:
        items = [b for b in items if b["sitter_id"] == sitter_id]
    if status_filter is not None:
        if status_filter not in _BG_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, f"Invalid status filter: {status_filter}")
        items = [b for b in items if b["status"] == status_filter]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([bg_to_dict(b) for b in page], limit, offset, total)


@bp.post("/api/v1/background-checks/<bid>/clear")
@require_auth(roles=["PlatformAdmin"])
def clear_bg(bid: str):
    bc = get_background_check_or_404(bid)
    if bc["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "BackgroundCheck must be PENDING to clear.")
    with db.lock:
        bc["status"] = "CLEARED"
        bc["cleared_at"] = db.fmt_ts(db.utcnow())
        bump(bc)
        # Side effect: Sitter BG_CHECK_PENDING -> ACTIVE
        sitter = db.sitters.get(bc["sitter_id"])
        if sitter is not None and sitter["status"] == "BG_CHECK_PENDING":
            sitter["status"] = "ACTIVE"
            bump(sitter)
    return response.ok(bg_to_dict(bc))


@bp.post("/api/v1/background-checks/<bid>/flag")
@require_auth(roles=["PlatformAdmin"])
def flag_bg(bid: str):
    bc = get_background_check_or_404(bid)
    if bc["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "BackgroundCheck must be PENDING to flag.")
    body = get_json_body()
    flagged_reason = require_str(body, "flagged_reason")
    with db.lock:
        bc["status"] = "FLAGGED"
        bc["flagged_reason"] = flagged_reason
        bump(bc)
        # Cascade #1
        sitter = db.sitters.get(bc["sitter_id"])
        if sitter is not None:
            cascade1_bg_check_flagged(sitter)
    return response.ok(bg_to_dict(bc))

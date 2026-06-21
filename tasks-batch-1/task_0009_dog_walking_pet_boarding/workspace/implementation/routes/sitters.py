"""Sitter routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_sitter_or_404
from services.sitter_logic import recompute_sitter_tier

bp = Blueprint("sitters", __name__)


_SITTER_STATUSES = {"APPLIED", "BG_CHECK_PENDING", "ACTIVE", "SUSPENDED", "DEACTIVATED"}
_SITTER_TIERS = {"BRONZE", "SILVER", "GOLD"}


def sitter_to_dict(s: dict) -> dict:
    return {
        "id": s["id"],
        "email": s["email"],
        "full_name": s["full_name"],
        "phone": s["phone"],
        "status": s["status"],
        "tier": s["tier"],
        "tier_score": s["tier_score"],
        "total_completed_bookings": s["total_completed_bookings"],
        "total_rating_sum": s["total_rating_sum"],
        "total_rating_count": s["total_rating_count"],
        "claim_count": s["claim_count"],
        "pending_payout_cents": s["pending_payout_cents"],
        "suspended_at": s["suspended_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.post("/api/v1/sitters/register")
@require_auth(roles=["Anonymous", "Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def register_sitter():
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone")

    for s in db.sitters.values():
        if s["email"] == email:
            raise ApiError(ERR_INVALID_REQUEST, "email already in use.")

    with db.lock:
        sitter = {
            **new_common_fields(),
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "status": "APPLIED",
            "tier": "BRONZE",
            "tier_score": 10,
            "total_completed_bookings": 0,
            "total_rating_sum": 0,
            "total_rating_count": 0,
            "claim_count": 0,
            "pending_payout_cents": 0,
            "suspended_at": None,
        }
        db.sitters[sitter["id"]] = sitter
    return response.ok(sitter_to_dict(sitter), status=201)


@bp.get("/api/v1/sitters/<sid>")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def get_sitter(sid: str):
    s = get_sitter_or_404(sid)
    return response.ok(sitter_to_dict(s))


@bp.get("/api/v1/sitters")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def list_sitters():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    tier_filter = request.args.get("tier")

    items = list(db.sitters.values())
    if status_filter is not None:
        if status_filter not in _SITTER_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, f"Invalid status filter: {status_filter}")
        items = [s for s in items if s["status"] == status_filter]
    if tier_filter is not None:
        if tier_filter not in _SITTER_TIERS:
            raise ApiError(ERR_INVALID_REQUEST, f"Invalid tier filter: {tier_filter}")
        items = [s for s in items if s["tier"] == tier_filter]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([sitter_to_dict(s) for s in page], limit, offset, total)


@bp.post("/api/v1/sitters/<sid>/reinstate")
@require_auth(roles=["PlatformAdmin"])
def reinstate_sitter(sid: str):
    s = get_sitter_or_404(sid)
    if s["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Sitter must be SUSPENDED to reinstate.")
    with db.lock:
        s["status"] = "ACTIVE"
        s["suspended_at"] = None
        bump(s)
    return response.ok(sitter_to_dict(s))


@bp.post("/api/v1/sitters/<sid>/deactivate")
@require_auth(roles=["PlatformAdmin"])
def deactivate_sitter(sid: str):
    s = get_sitter_or_404(sid)
    if s["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "Sitter must be ACTIVE or SUSPENDED to deactivate.")
    if s["status"] == "ACTIVE":
        # Cannot deactivate ACTIVE with any open booking
        blocking = {"REQUESTED", "CONFIRMED", "KEY_RECEIVED", "IN_PROGRESS"}
        for b in db.bookings.values():
            if b["sitter_id"] == sid and b["status"] in blocking:
                raise ApiError(
                    ERR_INVALID_STATE,
                    "Sitter has open bookings; cannot deactivate from ACTIVE.",
                )
    with db.lock:
        s["status"] = "DEACTIVATED"
        bump(s)
    return response.ok(sitter_to_dict(s))


@bp.post("/api/v1/sitters/<sid>/recompute-tier")
@require_auth(roles=["PlatformAdmin"])
def recompute_tier(sid: str):
    s = get_sitter_or_404(sid)
    with db.lock:
        recompute_sitter_tier(s)
    return response.ok(sitter_to_dict(s))

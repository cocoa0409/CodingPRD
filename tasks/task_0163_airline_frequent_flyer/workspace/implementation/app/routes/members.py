"""Member endpoints."""

from __future__ import annotations

from flask import Blueprint, g

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store, new_uuid
from ..timeutil import clock
from ..services.common import (
    get_json_body, require_fields, parse_pagination, paginate,
    bump_version, check_version, get_member_or_404, enforce_member_ownership,
)
from ..services.serialize import serialize_member


members_bp = Blueprint("members", __name__)


VALID_REGIONS = {"DOMESTIC", "INTERNATIONAL"}
VALID_TIERS = {"BASIC", "SILVER", "GOLD", "PLATINUM"}
VALID_STATUSES = {"ACTIVE", "FROZEN", "CLOSED"}


def _validate_member_create_body(body: dict) -> None:
    require_fields(body, "email", "display_name", "home_region")
    email = body["email"]
    if not isinstance(email, str) or "@" not in email or not email.strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid email.")
    if not isinstance(body["display_name"], str) or not body["display_name"].strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid display_name.")
    if body["home_region"] not in VALID_REGIONS:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid home_region.")


@members_bp.post("/members")
@require_roles("ProgramAdmin", "BookingAgent")
def create_member():
    body = get_json_body()
    _validate_member_create_body(body)
    email_norm = body["email"].strip().lower()
    if email_norm in store.member_email_index:
        raise E.ApiError(E.ERR_EMAIL_CONFLICT, 409, "Email already in use.")
    now = clock.now()
    mid = new_uuid()
    m = {
        "id": mid,
        "email": body["email"].strip(),
        "display_name": body["display_name"].strip(),
        "home_region": body["home_region"],
        "status": "ACTIVE",
        "tier": "BASIC",
        "tier_source": "EARNED",
        "tier_valid_through_year": now.year,
        "last_activity_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.members[mid] = m
    store.member_email_index[email_norm] = mid
    return ok_object(serialize_member(m, now), 201)


@members_bp.get("/members")
@require_roles("ProgramAdmin")
def list_members():
    from flask import request
    limit, offset = parse_pagination()
    tier_f = request.args.get("tier")
    status_f = request.args.get("status")
    items = [
        m for m in store.members.values()
        if (tier_f is None or m["tier"] == tier_f)
        and (status_f is None or m["status"] == status_f)
    ]
    items.sort(key=lambda m: m["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_member(m) for m in page]
    return ok_array(data, limit, offset, total, has_more)


@members_bp.get("/members/<member_id>")
@require_roles("Member", "ProgramAdmin", "BookingAgent")
def get_member(member_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    return ok_object(serialize_member(m))


@members_bp.patch("/members/<member_id>")
@require_roles("Member", "ProgramAdmin")
def patch_member(member_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    body = get_json_body()
    check_version(m, body)
    if "display_name" in body and body["display_name"] is not None:
        if not isinstance(body["display_name"], str) or not body["display_name"].strip():
            raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid display_name.")
        m["display_name"] = body["display_name"].strip()
    if "home_region" in body and body["home_region"] is not None:
        if body["home_region"] not in VALID_REGIONS:
            raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid home_region.")
        m["home_region"] = body["home_region"]
    bump_version(m)
    return ok_object(serialize_member(m))


@members_bp.post("/members/<member_id>/freeze")
@require_roles("ProgramAdmin")
def freeze_member(member_id):
    m = get_member_or_404(member_id)
    if m["status"] != "FROZEN":
        m["status"] = "FROZEN"
        bump_version(m)
    return ok_object(serialize_member(m))


@members_bp.post("/members/<member_id>/unfreeze")
@require_roles("ProgramAdmin")
def unfreeze_member(member_id):
    m = get_member_or_404(member_id)
    if m["status"] != "ACTIVE":
        m["status"] = "ACTIVE"
        bump_version(m)
    return ok_object(serialize_member(m))

"""Status Match request endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store, new_uuid
from ..timeutil import clock, add_months
from ..services.common import (
    get_json_body, require_fields, parse_pagination, paginate,
    bump_version, get_member_or_404, get_status_match_owned, enforce_member_ownership,
)
from ..services.serialize import serialize_status_match
from ..services import ledger
from ..services import tier as tier_svc
from ..services.upgrades import recompute_member_waitlist


status_match_bp = Blueprint("status_match", __name__)


VALID_TIERS = {"BASIC", "SILVER", "GOLD", "PLATINUM"}


@status_match_bp.post("/members/<member_id>/status-match-requests")
@require_roles("Member")
def submit_status_match(member_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    body = get_json_body()
    require_fields(body, "competitor_program", "competitor_tier", "evidence_url")
    if body["competitor_tier"] not in VALID_TIERS:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid competitor_tier.")
    if not isinstance(body["competitor_program"], str) or not body["competitor_program"].strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid competitor_program.")
    if not isinstance(body["evidence_url"], str) or not body["evidence_url"].strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid evidence_url.")
    now = clock.now()
    rid = new_uuid()
    r = {
        "id": rid,
        "member_id": member_id,
        "competitor_program": body["competitor_program"].strip(),
        "competitor_tier": body["competitor_tier"],
        "evidence_url": body["evidence_url"].strip(),
        "status": "PENDING",
        "granted_tier": None,
        "granted_at": None,
        "activated_at": None,
        "expires_at": None,
        "cooling_off_until": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.status_match_requests[rid] = r
    return ok_object(serialize_status_match(r), 201)


@status_match_bp.get("/members/<member_id>/status-match-requests")
@require_roles("Member", "ProgramAdmin")
def list_status_match(member_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    items = [
        r for r in store.status_match_requests.values()
        if r["member_id"] == member_id
        and (status_f is None or r["status"] == status_f)
    ]
    items.sort(key=lambda r: r["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_status_match(r) for r in page]
    return ok_array(data, limit, offset, total, has_more)


@status_match_bp.post("/members/<member_id>/status-match-requests/<rid>/approve")
@require_roles("ProgramAdmin")
def approve_status_match(member_id, rid):
    m = get_member_or_404(member_id)
    r = get_status_match_owned(member_id, rid)
    # State
    if r["status"] != "PENDING":
        raise E.ApiError(E.ERR_STATUS_MATCH_NOT_PENDING, 409, "Request is not PENDING.")
    now = clock.now()
    # Priority 6: cooling-off — any prior request whose cooling_off_until > now blocks
    for other in store.status_match_requests.values():
        if other["member_id"] != member_id:
            continue
        if other["id"] == rid:
            continue
        if other.get("cooling_off_until") and other["cooling_off_until"] > now:
            raise E.ApiError(E.ERR_STATUS_MATCH_COOLING_OFF, 409, "Cooling-off window active.")
    # Priority 7: ALREADY_ACTIVE — overlapping ACTIVE match
    if m["tier_source"] == "STATUS_MATCH":
        # member already has an active status-match-backed tier
        # find if any of their status-match requests are ACTIVE
        for other in store.status_match_requests.values():
            if other["member_id"] == member_id and other["status"] == "ACTIVE":
                raise E.ApiError(E.ERR_STATUS_MATCH_ALREADY_ACTIVE, 409,
                                 "Member already has an ACTIVE status-match.")
    # Approve
    granted = r["competitor_tier"]
    if tier_svc.rank(granted) > tier_svc.rank("PLATINUM"):
        granted = "PLATINUM"
    r["granted_tier"] = granted
    r["granted_at"] = now
    r["expires_at"] = add_months(now, 12)
    r["cooling_off_until"] = add_months(now, 36)
    r["status"] = "APPROVED"
    bump_version(r, now)
    return ok_object(serialize_status_match(r))


@status_match_bp.post("/members/<member_id>/status-match-requests/<rid>/reject")
@require_roles("ProgramAdmin")
def reject_status_match(member_id, rid):
    get_member_or_404(member_id)
    r = get_status_match_owned(member_id, rid)
    if r["status"] != "PENDING":
        raise E.ApiError(E.ERR_STATUS_MATCH_NOT_PENDING, 409, "Request is not PENDING.")
    r["status"] = "REJECTED"
    bump_version(r)
    return ok_object(serialize_status_match(r))


@status_match_bp.post("/members/<member_id>/status-match-requests/<rid>/activate")
@require_roles("Member", "ProgramAdmin")
def activate_status_match(member_id, rid):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    r = get_status_match_owned(member_id, rid)
    if r["status"] != "APPROVED":
        raise E.ApiError(E.ERR_STATUS_MATCH_NOT_APPROVED, 409, "Request is not APPROVED.")
    if tier_svc.rank(m["tier"]) >= tier_svc.rank(r["granted_tier"]):
        raise E.ApiError(E.ERR_MEMBER_TIER_INELIGIBLE, 403,
                         "Member tier is already at or above granted tier.")
    now = clock.now()
    r["status"] = "ACTIVE"
    r["activated_at"] = now
    bump_version(r, now)
    m["tier"] = r["granted_tier"]
    m["tier_source"] = "STATUS_MATCH"
    m["tier_valid_through_year"] = now.year
    bump_version(m, now)
    # Append STATUS_MATCH_BONUS = 5000
    ledger.append(
        member_id=member_id,
        kind="STATUS_MATCH_BONUS",
        points_delta=5000,
        posted_at=now,
        now=now,
    )
    m["last_activity_at"] = now
    bump_version(m, now)
    # Recompute all WAITLISTED upgrade requests' priority_score
    recompute_member_waitlist(member_id, m["tier"], lambda res: bump_version(res, now))
    return ok_object(serialize_status_match(r))

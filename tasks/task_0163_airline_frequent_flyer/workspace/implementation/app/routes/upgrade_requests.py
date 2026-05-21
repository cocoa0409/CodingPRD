"""Upgrade Request endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store, new_uuid
from ..timeutil import clock
from ..services.common import (
    get_json_body, require_fields, parse_pagination, paginate,
    bump_version, check_version, get_member_or_404, get_segment_owned,
    get_upgrade_or_404, enforce_member_ownership, enforce_member_status,
)
from ..services.serialize import (
    serialize_upgrade_request, compute_upgrade_inventory,
)
from ..services import calc, ledger
from ..services import tier as tier_svc


upgrade_requests_bp = Blueprint("upgrade_requests", __name__)


CABIN_ORDER = {"ECONOMY": 0, "BUSINESS": 1, "FIRST": 2}
VALID_TARGETS = {"BUSINESS", "FIRST"}


@upgrade_requests_bp.post("/members/<member_id>/segments/<segment_id>/upgrade-requests")
@require_roles("Member", "BookingAgent")
def create_upgrade_request(member_id, segment_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    s = get_segment_owned(member_id, segment_id)
    body = get_json_body()
    require_fields(body, "target_cabin", "points_offered")
    if body["target_cabin"] not in VALID_TARGETS:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid target_cabin.")
    if not isinstance(body["points_offered"], int) or body["points_offered"] < 0:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "points_offered must be a non-negative integer.")
    # State check: segment must be BOOKED
    if s["status"] != "BOOKED":
        raise E.ApiError(E.ERR_UPGRADE_NOT_WAITLISTED, 409, "Parent segment must be BOOKED.")
    # Cross-entity tier gate (priority 5)
    if not tier_svc.at_least(m["tier"], "GOLD"):
        raise E.ApiError(E.ERR_MEMBER_TIER_INELIGIBLE, 403, "Member tier must be at least GOLD.")
    # Target cabin must be strictly above booked_cabin
    if CABIN_ORDER[body["target_cabin"]] <= CABIN_ORDER[s["booked_cabin"]]:
        raise E.ApiError(E.ERR_TARGET_CABIN_NOT_UPGRADE, 409,
                         "target_cabin must be strictly higher than booked_cabin.")
    enforce_member_status(m)
    now = clock.now()
    # Assign waitlist_join_seq scoped to (flight_id, target_cabin)
    key = (s["flight_id"], body["target_cabin"])
    seq = store.waitlist_seq_by_flight_cabin.get(key, 0) + 1
    store.waitlist_seq_by_flight_cabin[key] = seq
    uid = new_uuid()
    u = {
        "id": uid,
        "member_id": member_id,
        "flight_segment_id": s["id"],
        "flight_id": s["flight_id"],
        "target_cabin": body["target_cabin"],
        "points_offered": body["points_offered"],
        "status": "WAITLISTED",
        "waitlist_join_seq": seq,
        "priority_score": 0,
        "held_points": body["points_offered"],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    u["priority_score"] = calc.priority_score(m["tier"], u["points_offered"], u["waitlist_join_seq"])
    store.upgrade_requests[uid] = u
    return ok_object(serialize_upgrade_request(u), 201)


@upgrade_requests_bp.get("/members/<member_id>/upgrade-requests")
@require_roles("Member", "ProgramAdmin")
def list_member_upgrade_requests(member_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    flight_f = request.args.get("flight_id")
    items = [
        u for u in store.upgrade_requests.values()
        if u["member_id"] == member_id
        and (status_f is None or u["status"] == status_f)
        and (flight_f is None or u["flight_id"] == flight_f)
    ]
    items.sort(key=lambda u: u["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_upgrade_request(u) for u in page]
    return ok_array(data, limit, offset, total, has_more)


@upgrade_requests_bp.patch("/upgrades/<upgrade_id>")
@require_roles("Member")
def patch_upgrade(upgrade_id):
    u = get_upgrade_or_404(upgrade_id)
    enforce_member_ownership(g.user_id, g.user_role, u["member_id"])
    if u["status"] != "WAITLISTED":
        raise E.ApiError(E.ERR_UPGRADE_NOT_WAITLISTED, 409, "Upgrade request is not WAITLISTED.")
    body = get_json_body()
    check_version(u, body)
    if "points_offered" not in body or body["points_offered"] is None:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "points_offered is required.")
    if not isinstance(body["points_offered"], int) or body["points_offered"] < 0:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "points_offered must be a non-negative integer.")
    m = store.members[u["member_id"]]
    u["points_offered"] = body["points_offered"]
    u["held_points"] = body["points_offered"]
    u["priority_score"] = calc.priority_score(m["tier"], u["points_offered"], u["waitlist_join_seq"])
    bump_version(u)
    return ok_object(serialize_upgrade_request(u))


@upgrade_requests_bp.post("/upgrades/<upgrade_id>/cancel")
@require_roles("Member")
def cancel_upgrade(upgrade_id):
    u = get_upgrade_or_404(upgrade_id)
    enforce_member_ownership(g.user_id, g.user_role, u["member_id"])
    if u["status"] != "WAITLISTED":
        raise E.ApiError(E.ERR_UPGRADE_NOT_WAITLISTED, 409, "Upgrade request is not WAITLISTED.")
    u["status"] = "CANCELLED"
    u["held_points"] = 0
    bump_version(u)
    return ok_object(serialize_upgrade_request(u))


@upgrade_requests_bp.post("/upgrades/<upgrade_id>/confirm")
@require_roles("ProgramAdmin")
def admin_confirm_upgrade(upgrade_id):
    u = get_upgrade_or_404(upgrade_id)
    if u["status"] != "WAITLISTED":
        raise E.ApiError(E.ERR_UPGRADE_NOT_WAITLISTED, 409, "Upgrade request is not WAITLISTED.")
    m = store.members[u["member_id"]]
    f = store.flights[u["flight_id"]]
    # Priority 5: tier gate
    if not tier_svc.at_least(m["tier"], "GOLD"):
        raise E.ApiError(E.ERR_MEMBER_TIER_INELIGIBLE, 403, "Member tier must be at least GOLD.")
    # Priority 7: inventory
    inv = compute_upgrade_inventory(f, u["target_cabin"])
    if inv <= 0:
        raise E.ApiError(E.ERR_UPGRADE_INVENTORY_EXHAUSTED, 409, "Upgrade inventory exhausted.")
    # Priority 8: points sufficiency
    from ..services.serialize import compute_points_balance
    now = clock.now()
    bal = compute_points_balance(m["id"], now)
    if bal < u["points_offered"]:
        raise E.ApiError(E.ERR_INSUFFICIENT_POINTS, 402, "Insufficient points.")
    # Side effects
    ledger.append(
        member_id=m["id"],
        kind="REDEMPTION",
        points_delta=-u["points_offered"],
        posted_at=now,
        related_segment_id=u["flight_segment_id"],
        now=now,
    )
    u["status"] = "CONFIRMED"
    u["held_points"] = u["points_offered"]
    bump_version(u, now)
    m["last_activity_at"] = now
    bump_version(m, now)
    return ok_object(serialize_upgrade_request(u))

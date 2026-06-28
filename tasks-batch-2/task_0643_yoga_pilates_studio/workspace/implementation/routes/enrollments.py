"""Enrollment endpoints: apply, confirm (OCC), withdraw."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import authenticate, require_roles
from models import make_enrollment, serialize, touch
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate, find_or_404)
from enroll_service import (recompute_workshop_count, recompute_workshop_posture,
                            capture_deposit, promote_earliest_waitlisted)

bp = Blueprint("enrollments", __name__)


@bp.post("/enrollments")
def apply_enrollment():
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    body = get_json_body()

    member_id = body.get("member_id")
    workshop_id = body.get("workshop_id")
    if not isinstance(member_id, str) or not member_id:
        raise err("ERR_INVALID_REQUEST", "member_id is required")
    if not isinstance(workshop_id, str) or not workshop_id:
        raise err("ERR_INVALID_REQUEST", "workshop_id is required")

    member = find_or_404(store.members, member_id, "Member")
    find_or_404(store.workshops, workshop_id, "Workshop")

    if principal.is_member and principal.user_id != member_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only enroll themselves")

    # Member standing.
    if member["account_status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member account is SUSPENDED")

    enrollment = make_enrollment(member_id, workshop_id)
    store.enrollments[enrollment["id"]] = enrollment
    return success(serialize(enrollment), status=201)


@bp.get("/enrollments/<eid>")
def get_enrollment(eid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    enrollment = find_or_404(store.enrollments, eid, "Enrollment")
    if principal.is_member and principal.user_id != enrollment["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only fetch their own enrollments")
    return success(serialize(enrollment))


@bp.get("/enrollments")
def list_enrollments():
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    limit, offset = parse_pagination()
    items = list(store.enrollments.values())
    if principal.is_member:
        items = [e for e in items if e["member_id"] == principal.user_id]
    for key in ("member_id", "workshop_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(e) for e in window], 200, limit, offset, total)


@bp.post("/enrollments/<eid>/confirm")
def confirm_enrollment(eid):
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    enrollment = find_or_404(store.enrollments, eid, "Enrollment")
    if principal.is_member and principal.user_id != enrollment["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only confirm their own enrollments")

    workshop = store.workshops.get(enrollment["workshop_id"])

    # State validity (priority 5).
    if enrollment["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Enrollment is not APPLIED")

    body = get_json_body()
    # OCC (priority 6): expected_workshop_version mandatory.
    if "expected_workshop_version" not in body or body["expected_workshop_version"] is None:
        raise err("ERR_VERSION_REQUIRED", "expected_workshop_version is required")
    expected = body["expected_workshop_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_workshop_version must be an integer")
    if workshop is None or expected != workshop["version"]:
        raise err("ERR_STALE_VERSION", "Workshop version mismatch")

    recompute_workshop_count(workshop)

    if workshop["status"] == "OPEN" and workshop["confirmed_seat_count"] < workshop["seat_capacity"]:
        enrollment["status"] = "CONFIRMED"
        capture_deposit(enrollment, workshop)
        touch(enrollment)
        workshop["confirmed_seat_count"] += 1
        if workshop["confirmed_seat_count"] >= workshop["seat_capacity"]:
            workshop["status"] = "FULL"
        touch(workshop)
        return success(serialize(enrollment))

    if workshop["status"] == "FULL":
        enrollment["status"] = "WAITLISTED"
        touch(enrollment)
        # Confirm still bumps the workshop version (a write occurred).
        touch(workshop)
        return success(serialize(enrollment))

    # OPEN but no confirmable seat (shouldn't normally happen) -> route to waitlist.
    enrollment["status"] = "WAITLISTED"
    touch(enrollment)
    touch(workshop)
    return success(serialize(enrollment))


@bp.post("/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    enrollment = find_or_404(store.enrollments, eid, "Enrollment")
    if principal.is_member and principal.user_id != enrollment["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only withdraw their own enrollments")

    workshop = store.workshops.get(enrollment["workshop_id"])

    if enrollment["status"] in ("APPLIED", "WAITLISTED"):
        enrollment["status"] = "WITHDRAWN"
        touch(enrollment)
        return success(serialize(enrollment))

    if enrollment["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Enrollment cannot be withdrawn from its current state")

    # CONFIRMED withdraw: deposit forfeited, balance zeroed, seat freed.
    enrollment["status"] = "WITHDRAWN"
    enrollment["balance_due_cents"] = 0
    # deposit_paid_cents is NOT refunded (kept on record as captured/forfeited).
    touch(enrollment)

    if workshop is not None:
        recompute_workshop_count(workshop)
        promoted = promote_earliest_waitlisted(workshop)
        recompute_workshop_count(workshop)
        if promoted is None:
            recompute_workshop_posture(workshop)
        else:
            # A promotion may keep it FULL; recompute posture either way.
            recompute_workshop_posture(workshop)

    return success(serialize(enrollment))

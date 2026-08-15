"""Group cohorts and membership (PRD §3.7)."""
from flask import Blueprint, request

from auth import authenticate, require_role, require_ownership, body, get_str, get_int
from db import store
from engine import (active_member_count, promote_waitlist_if_needed,
                    memberships_of_cohort)
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_COACH_NOT_CREDENTIALED, ERR_COHORT_NOT_JOINABLE,
                    not_found)
from serializers import cohort as ser_cohort, membership as ser_membership, base_row, append_row, touch
from timeutil import parse_date, now_iso

bp = Blueprint("cohorts", __name__)


def _get_cohort(cid):
    c = store.cohorts.get(cid)
    if c is None:
        raise not_found("Cohort not found")
    return c


@bp.post("/cohorts")
def create_cohort():
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    b = body()
    coach_id = b.get("coach_id")
    require_ownership(coach_id if isinstance(coach_id, str) else None, uid)
    title = get_str(b, "title")
    capacity = get_int(b, "capacity")
    ws = parse_date(b.get("window_start"))
    we = parse_date(b.get("window_end"))
    if (title is None or capacity is None or capacity < 2
            or ws is None or we is None):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: coach_id, title, capacity >= 2, window_start, window_end (ISO dates)")
    c = base_row()
    c.update({
        "coach_id": coach_id,
        "title": title,
        "capacity": capacity,
        "window_start": ws,
        "window_end": we,
        "cohort_status": "DRAFT",
    })
    store.cohorts[c["id"]] = c
    return success(ser_cohort(c)), 201


@bp.get("/cohorts/<cid>")
def get_cohort(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    return success(ser_cohort(_get_cohort(cid)))


@bp.get("/cohorts")
def list_cohorts():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.cohorts.values())
    coach_id = request.args.get("coach_id")
    status = request.args.get("cohort_status")
    if coach_id is not None:
        rows = [c for c in rows if c["coach_id"] == coach_id]
    if status is not None:
        rows = [c for c in rows if c["cohort_status"] == status]
    rows.sort(key=lambda c: (c["created_at"], c["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_cohort(c) for c in page], meta)


@bp.post("/cohorts/<cid>/open")
def open_cohort(cid):
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    c = _get_cohort(cid)
    require_ownership(c["coach_id"], uid)
    if c["cohort_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT cohort can be opened")
    # Priority 6: the credential gate applies to opening a cohort (PRD §2.7).
    coach = store.coaches.get(c["coach_id"])
    if (coach is None or coach["credential_status"] != "VERIFIED"
            or coach["ethics_status"] != "ACTIVE"):
        raise ApiError(ERR_COACH_NOT_CREDENTIALED, 422,
                       "Coach is not delivery-eligible (credential VERIFIED and ethics ACTIVE required)")
    c["cohort_status"] = "OPEN"
    touch(c)
    return success(ser_cohort(c))


@bp.post("/cohorts/<cid>/cancel")
def cancel_cohort(cid):
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    c = _get_cohort(cid)
    require_ownership(c["coach_id"], uid)
    if c["cohort_status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OPEN or IN_PROGRESS cohort can be cancelled")
    # Cohort flips first so waitlist promotion (gated on OPEN/IN_PROGRESS)
    # does not fire during the membership cascade.
    c["cohort_status"] = "CANCELLED"
    touch(c)
    for m in memberships_of_cohort(c["id"]):
        if m["member_status"] in ("ACTIVE", "WAITLISTED"):
            m["member_status"] = "REMOVED"
    for s in store.sessions.values():
        if s["cohort_id"] == c["id"] and s["session_status"] == "SCHEDULED":
            s["session_status"] = "CANCELLED"
            touch(s)
    return success(ser_cohort(c))


@bp.post("/cohorts/<cid>/members")
def add_member(cid):
    """ACTIVE if under capacity else WAITLISTED — a full cohort is a waitlist
    outcome, never an error (PRD §3.7)."""
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    c = _get_cohort(cid)
    require_ownership(c["coach_id"], uid)
    b = body()
    eid = b.get("enrollment_id")
    e = store.enrollments.get(eid) if isinstance(eid, str) else None
    if e is None:
        raise not_found("enrollment_id does not reference an existing enrollment")
    if e["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE enrollment can join a cohort")
    if c["cohort_status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError(ERR_COHORT_NOT_JOINABLE, 409,
                       "Cohort must be OPEN or IN_PROGRESS to accept members")
    if any(m["cohort_id"] == cid and m["enrollment_id"] == eid
           and m["member_status"] != "REMOVED"
           for m in store.memberships.values()):
        raise ApiError(ERR_COHORT_NOT_JOINABLE, 409,
                       "The enrollment already holds a live membership in this cohort")
    m = append_row()
    m.update({
        "cohort_id": cid,
        "enrollment_id": eid,
        "member_status": ("ACTIVE" if active_member_count(cid) < c["capacity"]
                          else "WAITLISTED"),
        "joined_at": now_iso(),
    })
    store.memberships[m["id"]] = m
    return success(ser_membership(m)), 201


@bp.get("/cohorts/<cid>/members")
def list_members(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    _get_cohort(cid)
    rows = memberships_of_cohort(cid)
    status = request.args.get("member_status")
    if status is not None:
        rows = [m for m in rows if m["member_status"] == status]
    rows.sort(key=lambda m: (m["created_at"], m["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_membership(m) for m in page], meta)


@bp.delete("/cohorts/<cid>/members/<mid>")
def remove_member(cid, mid):
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    c = _get_cohort(cid)
    m = store.memberships.get(mid)
    if m is None or m["cohort_id"] != cid:
        raise not_found("CohortMembership not found")
    require_ownership(c["coach_id"], uid)
    if m["member_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE membership can be removed")
    m["member_status"] = "REMOVED"
    # Promote the earliest WAITLISTED member if capacity freed (PRD §3.7).
    promote_waitlist_if_needed(c)
    return success(ser_membership(m))

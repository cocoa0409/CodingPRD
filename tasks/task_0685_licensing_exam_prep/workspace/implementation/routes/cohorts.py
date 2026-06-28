"""Cohort, CohortSession, CohortMembership routes (PRD §3.8)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db, stamp_create, touch
from response import success, list_success
from middleware import get_auth, require_role, pagination_params, paginate
from services import validate as V
from services.serialize import public, public_list
from services.lookups import (
    get_cohort, get_license_program, get_enrollment, get_membership,
    get_membership_scoped, assert_owner,
)
from services import enrollment_service as ES
from clock import parse_iso
from errors import raise_err
import errors

bp = Blueprint("cohorts", __name__)

SESSION_BUFFER_MINUTES = 30


def _parse_dt(value, field):
    if not isinstance(value, str) or value == "":
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string")
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a valid datetime")


# --------------------------------------------------------------------------- #
# Cohort CRUD
# --------------------------------------------------------------------------- #
@bp.post("/cohorts")
def create_cohort():
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    data = V.body()
    license_program_id = V.as_str(V.require(data, "license_program_id"),
                                  "license_program_id")
    title = V.as_str(V.require(data, "title"), "title")
    capacity = V.as_int(V.require(data, "capacity"), "capacity", minimum=1)
    get_license_program(license_program_id)
    rec = {
        "license_program_id": license_program_id,
        "title": title,
        "capacity": capacity,
        "seats_taken": 0,
        "status": "OPEN",
    }
    stamp_create(rec)
    db.cohorts[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/cohorts/<cid>")
def get_cohort_route(cid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    rec = get_cohort(cid)
    return success(public(rec))


@bp.get("/cohorts")
def list_cohorts():
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    limit, offset = pagination_params()
    rows = list(db.cohorts.values())
    lpid = request.args.get("license_program_id")
    if lpid is not None:
        rows = [r for r in rows if r["license_program_id"] == lpid]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


@bp.post("/cohorts/<cid>/close")
def close_cohort(cid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    rec = get_cohort(cid)
    if rec["status"] not in ("OPEN", "FULL"):
        raise_err(errors.ERR_INVALID_STATE, "cohort not OPEN/FULL")
    rec["status"] = "CLOSED"
    touch(rec)
    return success(public(rec))


# --------------------------------------------------------------------------- #
# Cohort sessions (buffer overlap)
# --------------------------------------------------------------------------- #
@bp.post("/cohorts/<cid>/sessions")
def create_session(cid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    get_cohort(cid)  # existence (priority 3)
    data = V.body()
    topic = V.as_str(V.require(data, "topic"), "topic")
    start = _parse_dt(V.require(data, "session_start_utc"), "session_start_utc")
    end = _parse_dt(V.require(data, "session_end_utc"), "session_end_utc")
    # session_end_utc MUST be strictly after session_start_utc
    if not (end > start):
        raise_err(errors.ERR_INVALID_REQUEST, "session_end_utc must be after start")
    # buffer overlap (priority 9.5): >= 30 min gap from every other session of cohort
    buffer = timedelta(minutes=SESSION_BUFFER_MINUTES)
    for s in db.cohort_sessions.values():
        if s["cohort_id"] != cid:
            continue
        es = parse_iso(s["session_start_utc"])
        ee = parse_iso(s["session_end_utc"])
        if start >= ee:
            gap = start - ee
        elif end <= es:
            gap = es - end
        else:
            # windows themselves overlap
            raise_err(errors.ERR_SESSION_BUFFER_CONFLICT, "session buffer conflict")
        if gap < buffer:
            raise_err(errors.ERR_SESSION_BUFFER_CONFLICT, "session buffer conflict")
    rec = {
        "cohort_id": cid,
        "topic": topic,
        "session_start_utc": data["session_start_utc"],
        "session_end_utc": data["session_end_utc"],
    }
    stamp_create(rec)
    db.cohort_sessions[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/cohorts/<cid>/sessions")
def list_sessions(cid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    get_cohort(cid)
    limit, offset = pagination_params()
    rows = [s for s in db.cohort_sessions.values() if s["cohort_id"] == cid]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


# --------------------------------------------------------------------------- #
# Cohort memberships
# --------------------------------------------------------------------------- #
@bp.post("/cohorts/<cid>/memberships")
def join_cohort(cid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    cohort = get_cohort(cid)
    data = V.body()
    enrollment_id = V.as_str(V.require(data, "enrollment_id"), "enrollment_id")
    start = _parse_dt(V.require(data, "session_start_utc"), "session_start_utc")
    end = _parse_dt(V.require(data, "session_end_utc"), "session_end_utc")
    enr = get_enrollment(enrollment_id)
    assert_owner(enr, user_id)
    if not (end > start):
        raise_err(errors.ERR_INVALID_REQUEST, "session_end_utc must be after start")
    # referential (priority 8): cohort program must match enrollment program
    if cohort["license_program_id"] != enr["license_program_id"]:
        raise_err(errors.ERR_REFERENCE_INCOMPATIBLE,
                  "cohort program does not match enrollment program")
    # window overlap (priority 9): half-open against other JOINED memberships of
    # the SAME enrollment, across all cohorts.
    for m in db.cohort_memberships.values():
        if m["enrollment_id"] != enrollment_id or m["status"] != "JOINED":
            continue
        ms = parse_iso(m["session_start_utc"])
        me = parse_iso(m["session_end_utc"])
        # overlap iff new_start < existing_end AND existing_start < new_end
        if start < me and ms < end:
            raise_err(errors.ERR_SESSION_WINDOW_CONFLICT, "session window conflict")
    # capacity (priority 12): reject when full or CLOSED
    if cohort["status"] == "CLOSED" or cohort["seats_taken"] >= cohort["capacity"]:
        raise_err(errors.ERR_COHORT_FULL, "cohort full or closed")
    rec = {
        "cohort_id": cid,
        "enrollment_id": enrollment_id,
        "session_start_utc": data["session_start_utc"],
        "session_end_utc": data["session_end_utc"],
        "status": "JOINED",
    }
    stamp_create(rec)
    db.cohort_memberships[rec["id"]] = rec
    # increment seats_taken; flip OPEN->FULL if at capacity
    ES.recompute_cohort_after_seat_change(cohort)
    return success(public(rec), status=201)


@bp.get("/cohorts/<cid>/memberships")
def list_cohort_memberships(cid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    get_cohort(cid)
    limit, offset = pagination_params()
    rows = [m for m in db.cohort_memberships.values() if m["cohort_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


@bp.delete("/cohorts/<cid>/memberships/<mid>")
def drop_membership(cid, mid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    cohort = get_cohort(cid)
    m = get_membership_scoped(cid, mid)
    enr = db.enrollments.get(m["enrollment_id"])
    if enr is None or enr["learner_id"] != user_id:
        raise_err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    if m["status"] != "JOINED":
        raise_err(errors.ERR_INVALID_STATE, "membership not JOINED")
    m["status"] = "DROPPED"
    touch(m)
    ES.recompute_cohort_after_seat_change(cohort)
    return success(public(m))


# --------------------------------------------------------------------------- #
# Cohort membership top-level reads
# --------------------------------------------------------------------------- #
@bp.get("/cohort-memberships/<mid>")
def get_membership_route(mid):
    user_id, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner", "ExamProctor"})
    rec = get_membership(mid)
    if role == "Learner":
        enr = db.enrollments.get(rec["enrollment_id"])
        if enr is None or enr["learner_id"] != user_id:
            raise_err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    return success(public(rec))


@bp.get("/cohort-memberships")
def list_memberships():
    user_id, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner", "ExamProctor"})
    limit, offset = pagination_params()
    rows = list(db.cohort_memberships.values())
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if role == "Learner":
        owned = {e["id"] for e in db.enrollments.values()
                 if e["learner_id"] == user_id}
        rows = [r for r in rows if r["enrollment_id"] in owned]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)

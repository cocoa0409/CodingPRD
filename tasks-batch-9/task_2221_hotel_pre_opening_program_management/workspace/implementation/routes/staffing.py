"""Hiring plan, hire and training session endpoints (PRD §3.6)."""
from flask import Blueprint

import clock
import db
import guards
import repo
import response
import tx
import validate as v
from db import db as store
from errors import ApiError
from middleware import ALL_ROLES, require
from services import derive

bp = Blueprint("staffing", __name__)

TURNOVER_BUFFER_SECONDS = 30 * 60


# ===========================================================================
# Hiring plans
# ===========================================================================

@bp.post("/pre-opening/hiring-plans")
@require("TalentManager", "ProgramDirector")
def create_plan():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    department = v.req_enum(body, "department", repo.DEPARTMENTS)
    headcount_target = v.req_int(body, "headcount_target", minimum=1)
    wave_raw, _wave = v.req_date(body, "wave_start_date")

    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)
    for existing in repo.plans_of(program_id):
        if existing["department"] == department:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A hiring plan for %s already exists for this program." % department)

    ts = db.stamp()
    plan = {
        "id": db.new_id(),
        "program_id": program_id,
        "department": department,
        "headcount_target": headcount_target,
        "wave_start_date": wave_raw,
        "offered_count": 0,
        "accepted_count": 0,
        "onboarded_count": 0,
        "staffing_ratio": 0.0,
        "readiness_flag": "NOT_READY",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.hiring_plans[plan["id"]] = plan
    derive.refresh(program)
    tx.commit()
    return response.created(repo.serialize(plan))


@bp.get("/pre-opening/programs/<program_id>/hiring-plans")
@require(*ALL_ROLES)
def list_plans(program_id):
    program = repo.get_program(program_id)
    department = v.q_enum("department", repo.DEPARTMENTS)
    readiness_flag = v.q_enum("readiness_flag", repo.READINESS_FLAGS)
    items = repo.plans_of(program["id"])
    if department:
        items = [p for p in items if p["department"] == department]
    if readiness_flag:
        items = [p for p in items if p["readiness_flag"] == readiness_flag]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


# ===========================================================================
# Hires
# ===========================================================================

def _check_session_eligibility(plan, session, hire_id=None):
    enrolled = derive.session_enrolled_count(session["id"], exclude_hire_id=hire_id)
    if enrolled + 1 > session["capacity"]:
        raise ApiError("ERR_TRAINING_SESSION_FULL")
    if session["department"] != "ALL" and session["department"] != plan["department"]:
        raise ApiError("ERR_TRAINING_DEPARTMENT_MISMATCH")


@bp.post("/pre-opening/hires")
@require("TalentManager")
def create_hire():
    body = v.body()
    hiring_plan_id = v.req_id(body, "hiring_plan_id")
    full_name = v.req_str(body, "full_name", 1, 120)
    hourly_rate_cents = v.req_number(body, "hourly_rate_cents", minimum=0, exclusive_min=True)
    scheduled_hours = v.req_number(body, "scheduled_hours_per_day", minimum=0.5, maximum=12)
    start_raw, start_date = v.req_date(body, "start_date")
    orientation_session_id = v.opt_id(body, "orientation_session_id")

    plan = repo.get_plan(hiring_plan_id)
    session = None
    if orientation_session_id is not None:
        session = repo.get_session(orientation_session_id)
        if session["program_id"] != plan["program_id"]:
            raise ApiError("ERR_CROSS_PROGRAM_REFERENCE",
                           "The orientation session belongs to another program.")
    program = repo.get_program(plan["program_id"])
    guards.ensure_not_stabilized(program)

    if start_date < clock.parse_date_strict(plan["wave_start_date"]):
        raise ApiError("ERR_START_BEFORE_WAVE")
    if session is not None:
        _check_session_eligibility(plan, session)
    if plan["offered_count"] + 1 > plan["headcount_target"]:
        raise ApiError("ERR_HEADCOUNT_EXCEEDED")

    ts = db.stamp()
    hire = {
        "id": db.new_id(),
        "hiring_plan_id": hiring_plan_id,
        "orientation_session_id": orientation_session_id,
        "full_name": full_name,
        "hourly_rate_cents": hourly_rate_cents,
        "scheduled_hours_per_day": scheduled_hours,
        "start_date": start_raw,
        "state": "OFFERED",
        "accrual_cents": 0,
        "onboarded_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.hires[hire["id"]] = hire
    derive.reconcile(program)
    tx.commit()
    return response.created(repo.serialize(hire))


@bp.get("/pre-opening/hires")
@require(*ALL_ROLES)
def list_hires():
    hiring_plan_id = v.q_str("hiring_plan_id")
    orientation_session_id = v.q_str("orientation_session_id")
    state = v.q_enum("state", repo.HIRE_STATES)
    items = db.sort_created(list(store.hires.values()))
    if hiring_plan_id:
        items = [h for h in items if h["hiring_plan_id"] == hiring_plan_id]
    if orientation_session_id:
        items = [h for h in items if h["orientation_session_id"] == orientation_session_id]
    if state:
        items = [h for h in items if h["state"] == state]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.get("/pre-opening/hires/<hire_id>")
@require(*ALL_ROLES)
def read_hire(hire_id):
    return response.ok(repo.serialize(repo.get_hire(hire_id)))


@bp.post("/pre-opening/hires/<hire_id>/respond")
@require("TalentManager")
def respond_hire(hire_id):
    body = v.body()
    decision = v.req_enum(body, "decision", ("ACCEPT", "DECLINE", "WITHDRAW"))
    hire = repo.get_hire(hire_id)
    program = repo.program_of_hire(hire)
    guards.ensure_not_stabilized(program)

    required = "ACCEPTED" if decision == "WITHDRAW" else "OFFERED"
    if hire["state"] != required:
        raise ApiError("ERR_INVALID_HIRE_STATE",
                       "A hire in state %s may not be %sed." % (hire["state"], decision.lower()))

    if decision == "ACCEPT":
        hire["state"] = "ACCEPTED"
    elif decision == "DECLINE":
        hire["state"] = "DECLINED"
    else:
        hire["state"] = "WITHDRAWN"
    derive.refresh(program)
    tx.commit()
    return response.ok(repo.serialize(hire))


@bp.post("/pre-opening/hires/<hire_id>/assign-orientation")
@require("TalentManager")
def assign_orientation(hire_id):
    body = v.body()
    orientation_session_id = v.req_id(body, "orientation_session_id")
    hire = repo.get_hire(hire_id)
    plan = repo.get_plan(hire["hiring_plan_id"])
    session = repo.get_session(orientation_session_id)
    if session["program_id"] != plan["program_id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE",
                       "The orientation session belongs to another program.")
    program = repo.get_program(plan["program_id"])
    guards.ensure_not_stabilized(program)
    if hire["state"] not in ("OFFERED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_HIRE_STATE",
                       "A hire in state %s may not be enrolled." % hire["state"])
    _check_session_eligibility(plan, session, hire_id=hire["id"])

    hire["orientation_session_id"] = orientation_session_id
    derive.reconcile(program)
    tx.commit()
    return response.ok(repo.serialize(hire))


@bp.post("/pre-opening/hires/<hire_id>/onboard")
@require("TalentManager")
def onboard_hire(hire_id):
    hire = repo.get_hire(hire_id)
    program = repo.program_of_hire(hire)
    guards.ensure_not_stabilized(program)
    if hire["state"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_HIRE_STATE",
                       "Only an ACCEPTED hire may be onboarded.")
    session = None
    if hire["orientation_session_id"]:
        session = store.training_sessions.get(hire["orientation_session_id"])
    if session is None or session["state"] != "COMPLETED":
        raise ApiError("ERR_ORIENTATION_NOT_COMPLETED")
    if clock.today() < clock.parse_date_strict(hire["start_date"]):
        raise ApiError("ERR_INVALID_HIRE_STATE",
                       "The hire's start_date has not arrived yet.")

    hire["state"] = "ONBOARDED"
    hire["onboarded_at"] = clock.fmt_instant(clock.now())
    derive.refresh(program)
    tx.commit()
    return response.ok(repo.serialize(hire))


# ===========================================================================
# Training sessions
# ===========================================================================

@bp.post("/pre-opening/training-sessions")
@require("TalentManager", "ProgramDirector")
def create_session():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    title = v.req_str(body, "title", 1, 120)
    training_room_code = v.req_str(body, "training_room_code", 1, 16)
    starts_raw, starts_at = v.req_instant(body, "starts_at")
    ends_raw, ends_at = v.req_instant(body, "ends_at")
    capacity = v.req_int(body, "capacity", minimum=1)
    department = v.opt_enum(body, "department", repo.SESSION_DEPARTMENTS, "ALL")
    if not ends_at > starts_at:
        raise v.bad("ends_at must be strictly after starts_at.")

    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)

    buffered_start = starts_at.timestamp() - TURNOVER_BUFFER_SECONDS
    buffered_end = ends_at.timestamp() + TURNOVER_BUFFER_SECONDS
    for other in repo.sessions_of(program_id):
        if other["training_room_code"] != training_room_code:
            continue
        if other["state"] not in ("SCHEDULED", "COMPLETED"):
            continue
        other_start = clock.parse_instant(other["starts_at"]).timestamp()
        other_end = clock.parse_instant(other["ends_at"]).timestamp()
        if buffered_start < other_end and other_start < buffered_end:
            raise ApiError("ERR_TRAINING_ROOM_CONFLICT")

    ts = db.stamp()
    session = {
        "id": db.new_id(),
        "program_id": program_id,
        "title": title,
        "department": department,
        "training_room_code": training_room_code,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "capacity": capacity,
        "enrolled_count": 0,
        "state": "SCHEDULED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.training_sessions[session["id"]] = session
    tx.commit()
    return response.created(repo.serialize(session))


@bp.get("/pre-opening/programs/<program_id>/training-sessions")
@require(*ALL_ROLES)
def list_sessions(program_id):
    program = repo.get_program(program_id)
    department = v.q_enum("department", repo.SESSION_DEPARTMENTS)
    state = v.q_enum("state", repo.SESSION_STATES)
    training_room_code = v.q_str("training_room_code")
    items = repo.sessions_of(program["id"])
    if department:
        items = [s for s in items if s["department"] == department]
    if state:
        items = [s for s in items if s["state"] == state]
    if training_room_code:
        items = [s for s in items if s["training_room_code"] == training_room_code]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.post("/pre-opening/training-sessions/<session_id>/complete")
@require("TalentManager")
def complete_session(session_id):
    session = repo.get_session(session_id)
    program = repo.get_program(session["program_id"])
    guards.ensure_not_stabilized(program)
    if session["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Only a SCHEDULED session may be completed.")
    if clock.now() < clock.parse_instant(session["ends_at"]):
        raise ApiError("ERR_TRAINING_SESSION_NOT_ENDED")

    session["state"] = "COMPLETED"
    derive.reconcile_sessions(program)
    tx.commit()
    return response.ok(repo.serialize(session))


@bp.post("/pre-opening/training-sessions/<session_id>/cancel")
@require("TalentManager")
def cancel_session(session_id):
    body = v.body()
    v.opt_str(body, "reason", 1, 500)
    session = repo.get_session(session_id)
    program = repo.get_program(session["program_id"])
    guards.ensure_not_stabilized(program)
    if session["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Only a SCHEDULED session may be cancelled.")
    if derive.session_enrolled_count(session["id"]) != 0:
        raise ApiError("ERR_TRAINING_SESSION_HAS_ENROLLMENTS")

    session["state"] = "CANCELLED"
    derive.reconcile_sessions(program)
    tx.commit()
    return response.ok(repo.serialize(session))

from flask import Blueprint, request

from db import store, base_record, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_HOS_LIMIT_EXCEEDED,
    ERR_JOB_ALREADY_FILLED,
    ERR_STALE_VERSION,
)
from middleware import auth, require_roles, require_owner
from response import ok_obj, paged
from services import (
    DEADHEAD_MODES,
    MAX_DUTY_MINUTES_PER_MONTH,
    projected_tour_minutes,
    on_duty_elapsed_now,
    recompute_cumulative,
    recompute_fatigue,
    penalty_rotate,
    slot_for_call,
    eligible_slots,
    open_shortage,
)
from validators import body, req_int, opt_int, opt_enum

bp = Blueprint("calls", __name__)


def _get_call(call_id):
    call = store.calls.get(call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Call '%s' not found." % call_id)
    return call


@bp.get("/api/calls")
def list_calls():
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller", "Employee"))
    rows = list(store.calls.values())
    job_id = request.args.get("job_id")
    if job_id is not None:
        rows = [c for c in rows if c["job_id"] == job_id]
    employee_id = request.args.get("employee_id")
    if employee_id is not None:
        rows = [c for c in rows if c["employee_id"] == employee_id]
    cs = request.args.get("call_status")
    if cs is not None:
        rows = [c for c in rows if c["call_status"] == cs]
    return paged(rows, request.args)


@bp.get("/api/calls/<call_id>")
def get_call(call_id):
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller", "Employee"))
    return ok_obj(_get_call(call_id))


@bp.post("/api/calls/<call_id>/accept")
def accept_call(call_id):
    data = body()
    expected_job_version = req_int(data, "expected_job_version")
    deadhead_minutes = opt_int(data, "deadhead_minutes", 0, min_value=0)
    deadhead_mode = opt_enum(data, "deadhead_mode", DEADHEAD_MODES, "NONE")
    uid, role = auth()
    require_roles(role, ("Employee",))
    call = _get_call(call_id)
    require_owner(uid, call["employee_id"])
    job = store.jobs.get(call["job_id"])
    emp = store.employees.get(call["employee_id"])
    # State gate (priority 5)
    if call["call_status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Call is not OFFERED.")
    if not store.now < call["expires_at"]:
        raise ApiError(ERR_INVALID_STATE, 409, "Call response window has closed.")
    if emp is None or emp["availability_status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Employee is not AVAILABLE.")
    # HOS forward-looking gate (priority 7; inclusive boundary)
    projected = (
        emp["cumulative_duty_minutes_month"]
        + on_duty_elapsed_now(emp["id"])
        + projected_tour_minutes(job["job_symbol"])
    )
    if projected > MAX_DUTY_MINUTES_PER_MONTH:
        raise ApiError(
            ERR_HOS_LIMIT_EXCEEDED, 422,
            "Projected monthly duty minutes exceed the 16560-minute cap.",
        )
    # Job capacity gate (priority 11)
    if job["filled_count"] >= job["crew_required"]:
        raise ApiError(ERR_JOB_ALREADY_FILLED, 422, "Job has no open seats.")
    # Optimistic concurrency guard (priority 14)
    if expected_job_version != job["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_job_version does not match the job's current version.",
        )
    # Side effects
    asg = base_record()
    asg.update({
        "job_id": job["id"],
        "employee_id": emp["id"],
        "call_id": call["id"],
        "assignment_status": "MARKED_UP",
        "on_duty_at": None,
        "off_duty_at": None,
        "deadhead_minutes": deadhead_minutes,
        "deadhead_mode": deadhead_mode,
    })
    store.assignments[asg["id"]] = asg
    job["filled_count"] += 1
    if job["filled_count"] == job["crew_required"]:
        job["job_status"] = "FILLED"
    touch(job)
    call["call_status"] = "ACCEPTED"
    call["responded_at"] = store.now
    touch(call)
    emp["availability_status"] = "ON_ASSIGNMENT"
    recompute_cumulative(emp["id"])
    recompute_fatigue(emp["id"])
    touch(emp)
    return ok_obj(asg, 201)


@bp.post("/api/calls/<call_id>/decline")
def decline_call(call_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    call = _get_call(call_id)
    require_owner(uid, call["employee_id"])
    if call["call_status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Call is not OFFERED.")
    call["call_status"] = "DECLINED"
    call["responded_at"] = store.now
    touch(call)
    # Penalty rotation, then shortage check (decline -> rotation -> shortage)
    slot = slot_for_call(call)
    if slot is not None:
        penalty_rotate(slot)
    job = store.jobs.get(call["job_id"])
    if (
        job is not None
        and job["filled_count"] < job["crew_required"]
        and not eligible_slots(job)
    ):
        open_shortage(job)
    return ok_obj(call)


@bp.post("/api/calls/<call_id>/no-answer")
def no_answer_call(call_id):
    _, role = auth()
    require_roles(role, ("CrewCaller",))
    call = _get_call(call_id)
    if call["call_status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Call is not OFFERED.")
    call["call_status"] = "NO_ANSWER"
    call["responded_at"] = store.now
    touch(call)
    slot = slot_for_call(call)
    if slot is not None:
        penalty_rotate(slot)
    return ok_obj(call)


@bp.post("/api/calls/<call_id>/rescind")
def rescind_call(call_id):
    _, role = auth()
    require_roles(role, ("CrewCaller",))
    call = _get_call(call_id)
    if call["call_status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Call is not OFFERED.")
    call["call_status"] = "RESCINDED"
    call["responded_at"] = store.now
    touch(call)
    # Railroad-initiated: no board rotation penalty.
    return ok_obj(call)

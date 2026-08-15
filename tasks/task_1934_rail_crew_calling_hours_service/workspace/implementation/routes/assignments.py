from datetime import timedelta

from flask import Blueprint, request

from db import store, base_record, touch, minutes_between
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TEMPORAL_WINDOW,
    ERR_PAY_INCOMPLETE,
)
from middleware import auth, require_roles, require_owner
from response import ok_obj, paged
from services import (
    EARLY_REPORT_WINDOW_MINUTES,
    recompute_cumulative,
    recompute_fatigue,
    open_rest,
)

bp = Blueprint("assignments", __name__)

ALL_ROLES = ("CrewManager", "CrewCaller", "Employee")


def _get_assignment(asg_id):
    asg = store.assignments.get(asg_id)
    if asg is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Assignment '%s' not found." % asg_id)
    return asg


@bp.get("/api/assignments")
def list_assignments():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    rows = list(store.assignments.values())
    for param in ("job_id", "employee_id", "call_id", "assignment_status"):
        v = request.args.get(param)
        if v is not None:
            rows = [a for a in rows if a[param] == v]
    return paged(rows, request.args)


@bp.get("/api/assignments/<asg_id>")
def get_assignment(asg_id):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok_obj(_get_assignment(asg_id))


@bp.post("/api/assignments/<asg_id>/on-duty")
def on_duty(asg_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    asg = _get_assignment(asg_id)
    require_owner(uid, asg["employee_id"])
    if asg["assignment_status"] != "MARKED_UP":
        raise ApiError(ERR_INVALID_STATE, 409, "Assignment is not MARKED_UP.")
    job = store.jobs.get(asg["job_id"])
    if job is not None and store.now < job["report_time"] - timedelta(minutes=EARLY_REPORT_WINDOW_MINUTES):
        raise ApiError(
            ERR_TEMPORAL_WINDOW, 422,
            "Cannot go on duty earlier than 60 minutes before report_time.",
        )
    asg["assignment_status"] = "ON_DUTY"
    asg["on_duty_at"] = store.now
    touch(asg)
    emp = store.employees.get(asg["employee_id"])
    if emp is not None:
        before = emp["cumulative_duty_minutes_month"]
        recompute_cumulative(emp["id"])
        if emp["cumulative_duty_minutes_month"] != before:
            touch(emp)
    return ok_obj(asg)


@bp.post("/api/assignments/<asg_id>/tie-up")
def tie_up(asg_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    asg = _get_assignment(asg_id)
    require_owner(uid, asg["employee_id"])
    if asg["assignment_status"] != "ON_DUTY":
        raise ApiError(ERR_INVALID_STATE, 409, "Assignment is not ON_DUTY.")
    asg["assignment_status"] = "TIE_UP_PENDING"
    asg["off_duty_at"] = store.now
    touch(asg)
    emp = store.employees.get(asg["employee_id"])
    if emp is not None and emp["availability_status"] == "ON_ASSIGNMENT":
        emp["availability_status"] = "ON_REST"
        open_rest(emp["id"])
        recompute_cumulative(emp["id"])
        recompute_fatigue(emp["id"])
        touch(emp)
    # Auto-create the DRAFT pay record for this tour.
    pr = base_record()
    pr.update({
        "employee_id": asg["employee_id"],
        "assignment_id": asg["id"],
        "claimed_minutes": minutes_between(asg["on_duty_at"], asg["off_duty_at"]),
        "claimed_deadhead_minutes": asg["deadhead_minutes"],
        "gross_pay_cents": 0,
        "record_status": "DRAFT",
    })
    store.pay_records[pr["id"]] = pr
    store.auto_pay[asg["id"]] = pr["id"]
    return ok_obj(asg)


@bp.post("/api/assignments/<asg_id>/lay-off")
def lay_off_assignment(asg_id):
    uid, role = auth()
    require_roles(role, ("Employee",))
    asg = _get_assignment(asg_id)
    require_owner(uid, asg["employee_id"])
    if asg["assignment_status"] != "MARKED_UP":
        raise ApiError(ERR_INVALID_STATE, 409, "Assignment is not MARKED_UP.")
    job = store.jobs.get(asg["job_id"])
    if job is not None and not store.now < job["report_time"]:
        raise ApiError(
            ERR_TEMPORAL_WINDOW, 422,
            "Cannot lay off at or after the job's report_time.",
        )
    asg["assignment_status"] = "LAID_OFF"
    touch(asg)
    if job is not None:
        job["filled_count"] -= 1
        if job["job_status"] == "FILLED" and job["filled_count"] < job["crew_required"]:
            job["job_status"] = "CALLING"
        touch(job)
    emp = store.employees.get(asg["employee_id"])
    if emp is not None and emp["availability_status"] == "ON_ASSIGNMENT":
        # Mark-up path with no rest opening: duty never started.
        emp["availability_status"] = "AVAILABLE"
        touch(emp)
    return ok_obj(asg)


@bp.post("/api/assignments/<asg_id>/complete")
def complete_assignment(asg_id):
    _, role = auth()
    require_roles(role, ("CrewCaller",))
    asg = _get_assignment(asg_id)
    if asg["assignment_status"] != "TIE_UP_PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Assignment is not TIE_UP_PENDING.")
    pr_id = store.auto_pay.get(asg["id"])
    pr = store.pay_records.get(pr_id) if pr_id else None
    if pr is None or pr["record_status"] not in ("SUBMITTED", "FINALIZED"):
        raise ApiError(
            ERR_PAY_INCOMPLETE, 422,
            "The assignment's pay record must be SUBMITTED or FINALIZED.",
        )
    asg["assignment_status"] = "COMPLETED"
    touch(asg)
    job = store.jobs.get(asg["job_id"])
    if job is not None:
        job["filled_count"] -= 1
        touch(job)
    return ok_obj(asg)

from flask import Blueprint, request

from db import store, base_record, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REFERENTIAL_MISMATCH,
    ERR_HOS_LIMIT_EXCEEDED,
)
from middleware import auth, require_roles
from response import ok_obj, paged
from services import (
    MAX_DUTY_MINUTES_PER_MONTH,
    FATIGUE_BLOCK_THRESHOLD,
    projected_tour_minutes,
    on_duty_elapsed_now,
    recompute_cumulative,
    recompute_fatigue,
    open_rest,
)
from validators import body, req_str, opt_int

bp = Blueprint("shortages", __name__)

MGMT_ROLES = ("CrewManager", "CrewCaller")


def _get_shortage(sh_id):
    sh = store.shortages.get(sh_id)
    if sh is None:
        raise ApiError(ERR_NOT_FOUND, 404, "CrewShortage '%s' not found." % sh_id)
    return sh


@bp.post("/api/crew-shortages/<sh_id>/begin-recrew")
def begin_recrew(sh_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    sh = _get_shortage(sh_id)
    if sh["shortage_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "CrewShortage is not OPEN.")
    sh["shortage_status"] = "RECREWING"
    touch(sh)
    return ok_obj(sh)


@bp.post("/api/crew-shortages/<sh_id>/resolve")
def resolve_shortage(sh_id):
    data = body()
    assignment_id = req_str(data, "assignment_id")
    relieving_employee_id = req_str(data, "relieving_employee_id")
    deadhead_minutes = opt_int(data, "deadhead_minutes", 0, min_value=0)
    _, role = auth()
    require_roles(role, ("CrewManager",))
    sh = _get_shortage(sh_id)
    if sh["shortage_status"] != "RECREWING":
        raise ApiError(ERR_INVALID_STATE, 409, "CrewShortage is not RECREWING.")
    asg = store.assignments.get(assignment_id)
    if asg is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Assignment '%s' not found." % assignment_id)
    reliever = store.employees.get(relieving_employee_id)
    if reliever is None:
        raise ApiError(
            ERR_NOT_FOUND, 404,
            "Employee '%s' not found." % relieving_employee_id,
        )
    if asg["job_id"] != sh["job_id"]:
        raise ApiError(
            ERR_REFERENTIAL_MISMATCH, 422,
            "The assignment does not belong to this shortage's job.",
        )
    if asg["assignment_status"] != "ON_DUTY":
        raise ApiError(ERR_INVALID_STATE, 409, "Target assignment is not ON_DUTY.")
    if reliever["availability_status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Relieving employee is not AVAILABLE.")
    job = store.jobs.get(sh["job_id"])
    projected = (
        reliever["cumulative_duty_minutes_month"]
        + on_duty_elapsed_now(reliever["id"])
        + projected_tour_minutes(job["job_symbol"] if job else None)
    )
    if projected > MAX_DUTY_MINUTES_PER_MONTH:
        raise ApiError(
            ERR_HOS_LIMIT_EXCEEDED, 422,
            "Relieving employee would exceed the monthly hours-of-service cap.",
        )
    if reliever["fatigue_score"] >= FATIGUE_BLOCK_THRESHOLD:
        raise ApiError(
            ERR_HOS_LIMIT_EXCEEDED, 422,
            "Relieving employee is fatigue-blocked.",
        )
    # Relieve the target assignment (Assignment ON_DUTY -> RECREWED).
    asg["assignment_status"] = "RECREWED"
    asg["off_duty_at"] = store.now
    touch(asg)
    relieved = store.employees.get(asg["employee_id"])
    if relieved is not None and relieved["availability_status"] == "ON_ASSIGNMENT":
        relieved["availability_status"] = "ON_REST"
        open_rest(relieved["id"])
        recompute_cumulative(relieved["id"])
        recompute_fatigue(relieved["id"])
        touch(relieved)
    # Replacement assignment created directly in ON_DUTY.
    repl = base_record()
    repl.update({
        "job_id": sh["job_id"],
        "employee_id": reliever["id"],
        "call_id": None,
        "assignment_status": "ON_DUTY",
        "on_duty_at": store.now,
        "off_duty_at": None,
        "deadhead_minutes": deadhead_minutes,
        "deadhead_mode": "NONE",
    })
    store.assignments[repl["id"]] = repl
    reliever["availability_status"] = "ON_ASSIGNMENT"
    recompute_cumulative(reliever["id"])
    recompute_fatigue(reliever["id"])
    touch(reliever)
    sh["shortage_status"] = "RESOLVED"
    sh["resolved_at"] = store.now
    touch(sh)
    return ok_obj(sh)


@bp.post("/api/crew-shortages/<sh_id>/escalate")
def escalate_shortage(sh_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    sh = _get_shortage(sh_id)
    if sh["shortage_status"] not in ("OPEN", "RECREWING"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "CrewShortage is not OPEN or RECREWING.",
        )
    sh["shortage_status"] = "ESCALATED"
    touch(sh)
    return ok_obj(sh)


@bp.get("/api/crew-shortages")
def list_shortages():
    _, role = auth()
    require_roles(role, MGMT_ROLES)
    rows = list(store.shortages.values())
    job_id = request.args.get("job_id")
    if job_id is not None:
        rows = [s for s in rows if s["job_id"] == job_id]
    ss = request.args.get("shortage_status")
    if ss is not None:
        rows = [s for s in rows if s["shortage_status"] == ss]
    return paged(rows, request.args)


@bp.get("/api/crew-shortages/<sh_id>")
def get_shortage(sh_id):
    _, role = auth()
    require_roles(role, MGMT_ROLES)
    return ok_obj(_get_shortage(sh_id))

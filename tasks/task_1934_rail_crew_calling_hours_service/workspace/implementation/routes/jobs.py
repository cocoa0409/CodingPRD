from datetime import timedelta

from flask import Blueprint, request

from db import store, base_record, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_REFERENTIAL_MISMATCH,
    ERR_CALL_POOL_EXHAUSTED,
)
from middleware import auth, require_roles
from response import ok_obj, paged
from services import (
    CRAFTS,
    CALL_RESPONSE_WINDOW_MINUTES,
    matching_boards_exist,
    eligible_slots,
    open_shortage,
)
from validators import body, req_str, req_enum, req_dt, req_int

bp = Blueprint("jobs", __name__)


def _get_job(job_id):
    job = store.jobs.get(job_id)
    if job is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Job '%s' not found." % job_id)
    return job


@bp.post("/api/jobs")
def create_job():
    data = body()
    job_symbol = req_str(data, "job_symbol")
    craft = req_enum(data, "craft", CRAFTS)
    origin_terminal = req_str(data, "origin_terminal")
    report_time = req_dt(data, "report_time")
    crew_required = req_int(data, "crew_required", min_value=1)
    _, role = auth()
    require_roles(role, ("CrewManager",))
    rec = base_record()
    rec.update({
        "job_symbol": job_symbol,
        "craft": craft,
        "origin_terminal": origin_terminal,
        "report_time": report_time,
        "crew_required": crew_required,
        "filled_count": 0,
        "job_status": "BULLETINED",
    })
    store.jobs[rec["id"]] = rec
    return ok_obj(rec, 201)


@bp.get("/api/jobs")
def list_jobs():
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller", "Employee"))
    rows = list(store.jobs.values())
    craft = request.args.get("craft")
    if craft is not None:
        rows = [r for r in rows if r["craft"] == craft]
    js = request.args.get("job_status")
    if js is not None:
        rows = [r for r in rows if r["job_status"] == js]
    return paged(rows, request.args)


@bp.get("/api/jobs/<job_id>")
def get_job(job_id):
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller", "Employee"))
    return ok_obj(_get_job(job_id))


@bp.post("/api/jobs/<job_id>/calls")
def issue_call(job_id):
    _, role = auth()
    require_roles(role, ("CrewCaller",))
    job = _get_job(job_id)
    if job["job_status"] not in ("BULLETINED", "CALLING"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Job must be BULLETINED or CALLING to issue a call.",
        )
    if not matching_boards_exist(job):
        raise ApiError(
            ERR_REFERENTIAL_MISMATCH, 422,
            "No extra board matches the job's craft and origin terminal.",
        )
    pool = eligible_slots(job)
    if not pool:
        open_shortage(job)
        raise ApiError(
            ERR_CALL_POOL_EXHAUSTED, 422,
            "No eligible callee; a crew shortage has been opened.",
        )
    slot = pool[0]
    call = base_record()
    call.update({
        "job_id": job["id"],
        "employee_id": slot["employee_id"],
        "call_status": "OFFERED",
        "offered_at": store.now,
        "expires_at": store.now + timedelta(minutes=CALL_RESPONSE_WINDOW_MINUTES),
        "responded_at": None,
    })
    store.calls[call["id"]] = call
    if job["job_status"] != "CALLING":
        job["job_status"] = "CALLING"
        touch(job)
    return ok_obj(call, 201)


@bp.get("/api/jobs/<job_id>/calls")
def list_job_calls(job_id):
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller"))
    _get_job(job_id)
    rows = [c for c in store.calls.values() if c["job_id"] == job_id]
    cs = request.args.get("call_status")
    if cs is not None:
        rows = [c for c in rows if c["call_status"] == cs]
    return paged(rows, request.args)


@bp.post("/api/jobs/<job_id>/crew-shortages")
def declare_shortage(job_id):
    _, role = auth()
    require_roles(role, ("CrewManager",))
    job = _get_job(job_id)
    sh = open_shortage(job)
    return ok_obj(sh, 201)

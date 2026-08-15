"""Job endpoints."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_DRAWING_NOT_APPROVED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEQUENCE_NOT_RELEASED,
)
from store import new_record, store, touch
from validate import (
    authenticate,
    get_body,
    opt_bool,
    req_enum,
    req_pos_int,
    req_str,
    require_role,
)
from . import list_response

bp = Blueprint("jobs", __name__)

ADMIN = {"FABRICATOR_ADMIN"}


def get_job_or_404(job_id):
    job = store.jobs.get(job_id)
    if job is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    return job


@bp.post("/jobs")
def create_job():
    authenticate_role = authenticate()
    require_role(authenticate_role[1], ADMIN)
    body = get_body()
    name = req_str(body, "name")
    contract_value_cents = req_pos_int(body, "contract_value_cents")
    billing_basis = req_enum(body, "billing_basis", ("WEIGHT", "COUNT"))
    requires_aisc_hold = opt_bool(body, "requires_aisc_hold", False)
    job = new_record()
    job.update(
        {
            "name": name,
            "contract_value_cents": contract_value_cents,
            "billing_basis": billing_basis,
            "requires_aisc_hold": requires_aisc_hold,
            "status": "ESTIMATING",
            "retainage_releasable_cents": 0,
        }
    )
    store.jobs[job["id"]] = job
    return ok_object(domain.job_view(job), 201)


@bp.get("/jobs")
def list_jobs():
    uid, role = authenticate()
    require_role(role, ADMIN | {"DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"})
    return list_response(store.jobs.values(), domain.job_view, [("status", "status")])


@bp.get("/jobs/<jid>")
def get_job(jid):
    uid, role = authenticate()
    require_role(role, ADMIN | {"DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"})
    return ok_object(domain.job_view(get_job_or_404(jid)))


@bp.post("/jobs/<jid>/award")
def award_job(jid):
    uid, role = authenticate()
    require_role(role, ADMIN)
    job = get_job_or_404(jid)
    if job["status"] != "ESTIMATING":
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be ESTIMATING to award.")
    job["status"] = "AWARDED"
    touch(job)
    return ok_object(domain.job_view(job))


@bp.post("/jobs/<jid>/start-fabrication")
def start_fabrication(jid):
    uid, role = authenticate()
    require_role(role, ADMIN)
    job = get_job_or_404(jid)
    if job["status"] != "AWARDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be AWARDED to start fabrication.")
    if not any(
        d for d in store.drawings.values() if d["job_id"] == jid and d["status"] == "APPROVED"
    ):
        raise ApiError(
            ERR_DRAWING_NOT_APPROVED, 409, "At least one drawing of the job must be APPROVED."
        )
    job["status"] = "FABRICATING"
    touch(job)
    return ok_object(domain.job_view(job))


@bp.post("/jobs/<jid>/start-erection")
def start_erection(jid):
    uid, role = authenticate()
    require_role(role, ADMIN)
    job = get_job_or_404(jid)
    if job["status"] != "FABRICATING":
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be FABRICATING to start erection.")
    if not any(
        s for s in store.sequences.values() if s["job_id"] == jid and s["status"] == "RELEASED"
    ):
        raise ApiError(
            ERR_SEQUENCE_NOT_RELEASED, 409, "At least one sequence of the job must be RELEASED."
        )
    job["status"] = "ERECTING"
    touch(job)
    return ok_object(domain.job_view(job))

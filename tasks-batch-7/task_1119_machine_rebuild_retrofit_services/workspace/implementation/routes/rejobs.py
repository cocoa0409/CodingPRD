"""ReverseEngineeringJob endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import bump, sorted_records, store
from errors import ApiError, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES
from middleware import require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from util import get_body, pagination_params, paginate, req_int
from routes.common import get_or_404

bp = Blueprint("rejobs", __name__)


@bp.get("/api/re-jobs/<jid>")
@require_roles("RebuildEngineer", "QualityInspector", "ProjectManager", "PlatformAdmin")
def get_re_job(user_id, role, jid):
    rec = get_or_404(store.re_jobs, jid, "reverse-engineering job")
    return success(serialize(rec))


@bp.get("/api/re-jobs")
@require_roles("RebuildEngineer", "QualityInspector", "ProjectManager", "PlatformAdmin")
def list_re_jobs(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.re_jobs)
    for param in ("part_line_id", "project_id", "part_id"):
        value = request.args.get(param)
        if value is not None:
            items = [j for j in items if j[param] == value]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


@bp.post("/api/re-jobs/<jid>/capture-spec")
@require_roles("RebuildEngineer")
def capture_spec(user_id, role, jid):
    job = get_or_404(store.re_jobs, jid, "reverse-engineering job")
    if job["status"] != "REQUESTED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"job in status {job['status']} cannot capture a spec",
            409,
        )
    job["status"] = "SPEC_CAPTURED"
    bump(job)
    return success(serialize(job))


@bp.post("/api/re-jobs/<jid>/fabricate")
@require_roles("RebuildEngineer")
def fabricate(user_id, role, jid):
    body = get_body()
    re_cost_cents = req_int(body, "re_cost_cents", minimum=0)
    job = get_or_404(store.re_jobs, jid, "reverse-engineering job")
    if job["status"] != "SPEC_CAPTURED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"job in status {job['status']} cannot be fabricated",
            409,
        )
    job["status"] = "PROTOTYPE_FABRICATED"
    job["fabricated_by_id"] = user_id
    job["re_cost_cents"] = re_cost_cents
    bump(job)
    return success(serialize(job))


def _check_segregation(job, user_id):
    if job["fabricated_by_id"] is not None and job["fabricated_by_id"] == user_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "the validator must differ from the job's fabricator",
            403,
        )


@bp.post("/api/re-jobs/<jid>/validate")
@require_roles("QualityInspector")
def validate(user_id, role, jid):
    job = get_or_404(store.re_jobs, jid, "reverse-engineering job")
    _check_segregation(job, user_id)
    if job["status"] != "PROTOTYPE_FABRICATED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"job in status {job['status']} cannot be validated",
            409,
        )
    job["status"] = "VALIDATED"
    job["validated_by_id"] = user_id
    bump(job)
    line = store.part_lines.get(job["part_line_id"])
    if line is not None and line["status"] == "RE_PENDING":
        line["status"] = "RE_FULFILLED"
        bump(line)
    return success(serialize(job))


@bp.post("/api/re-jobs/<jid>/fail")
@require_roles("QualityInspector")
def fail(user_id, role, jid):
    job = get_or_404(store.re_jobs, jid, "reverse-engineering job")
    _check_segregation(job, user_id)
    if job["status"] != "PROTOTYPE_FABRICATED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"job in status {job['status']} cannot be failed",
            409,
        )
    job["status"] = "SPEC_CAPTURED"
    job["revision_count"] += 1
    bump(job)
    return success(serialize(job))

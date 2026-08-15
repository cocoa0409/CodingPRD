"""PackagingJob endpoints: label verification and completion (goods-lot birth)."""
from flask import Blueprint

from db import new_common, new_id, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import ok, paginate
from validation import parse_body, require_path_entity

bp = Blueprint("packaging", __name__)


@bp.get("/packaging-jobs")
def list_jobs():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.packaging_jobs.values())
    rows = paginate.filter(rows, "run_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/packaging-jobs/<job_id>")
def get_job(job_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.packaging_jobs, job_id,
                                  "ERR_PACKAGING_JOB_NOT_FOUND"))


@bp.post("/packaging-jobs/<job_id>/verify-labels")
def verify_labels(job_id):
    uid, role, _ = get_context()
    require_roles(["QAManager"])
    job = require_path_entity(store.packaging_jobs, job_id, "ERR_PACKAGING_JOB_NOT_FOUND")
    if job["status"] != "CREATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "verify-labels requires a CREATED packaging job")
    run = store.production_runs[job["run_id"]]
    if run["brand_type"] != "PRIVATE_LABEL":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Label verification exists only for PRIVATE_LABEL jobs")
    job["status"] = "LABEL_VERIFIED"
    job["labels_verified_by_user_id"] = uid
    touch(job)
    return ok(job)


@bp.post("/packaging-jobs/<job_id>/complete")
def complete_job(job_id):
    get_context()
    require_roles(["ProductionOperator"])
    job = require_path_entity(store.packaging_jobs, job_id, "ERR_PACKAGING_JOB_NOT_FOUND")
    if job["status"] not in ("CREATED", "LABEL_VERIFIED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "complete requires a CREATED or LABEL_VERIFIED packaging job")
    run = store.production_runs[job["run_id"]]
    if run["brand_type"] == "PRIVATE_LABEL" and job["status"] != "LABEL_VERIFIED":
        raise ApiError("ERR_LABEL_VERIFICATION_REQUIRED", 409,
                       "Private-label job must be LABEL_VERIFIED before completion")
    job["status"] = "COMPLETED"
    touch(job)
    goods = {
        "id": new_id(),
        "packaging_job_id": job["id"],
        "run_id": run["id"],
        "zone_id": None,
        "production_date": None,   # stamped when the run reaches COMPLETED
        "expiry_date": None,
        "case_count": job["case_count"],
        "pallet_count": job["pallet_count"],
        "unit_count": (job["full_case_count"] * job["units_per_case"]
                       + ((job["total_units"]
                           - job["full_case_count"] * job["units_per_case"])
                          if job["partial_case_count"] == 1 else 0)),
        "gluten_free": run["gluten_free"],
        "brand_type": run["brand_type"],
        "status": "CREATED",
        "_occupying": False,
    }
    new_common(goods)
    store.finished_goods_lots[goods["id"]] = goods
    return ok(job)

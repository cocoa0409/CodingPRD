"""JobLevelTarget routes: the target-bonus grid and the manager guideline band."""

from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import (BUSINESS_UNIT_MANAGER, COMPENSATION_COMMITTEE,
                        FINANCE_CONTROLLER, HR_BUSINESS_PARTNER, PLAN_ADMIN,
                        authenticate, get_body, query_param, req_id,
                        req_number, req_percent, req_string, quantize2)
from response import object_response
from routes.common import paginated
from serialize import job_level_target_out
from services import lookup

bp = Blueprint("job_level_targets", __name__)

READ_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
              HR_BUSINESS_PARTNER, FINANCE_CONTROLLER]
SETUP_STATUSES = ("DRAFT", "TARGETS_SET")
RATIO_CEILING = Decimal("5")


@bp.route("/job-level-targets", methods=["POST"])
def create_job_level_target():
    authenticate([PLAN_ADMIN])
    body = get_body()

    plan_id = req_id(body, "plan_id")
    job_level = req_string(body, "job_level")
    target_pct = req_percent(body, "target_bonus_pct", minimum="0.01", maximum=200)
    min_ratio = quantize2(req_number(body, "guideline_min_ratio"))
    max_ratio = quantize2(req_number(body, "guideline_max_ratio"))

    plan = lookup.plan(plan_id)

    if not (Decimal("0") <= min_ratio < max_ratio <= RATIO_CEILING):
        raise ApiError("ERR_GUIDELINE_BAND_INVALID")
    for existing in db.plan_targets(plan_id):
        if existing["job_level"] == job_level:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "Job level '%s' already has a target in this plan" % job_level)
    if plan["status"] not in SETUP_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_SETUP")

    target = db.base_record()
    target.update({
        "plan_id": plan_id,
        "job_level": job_level,
        "target_bonus_pct": target_pct,
        "guideline_min_ratio": min_ratio,
        "guideline_max_ratio": max_ratio,
    })
    db.job_level_targets[target["id"]] = target
    return object_response(job_level_target_out(target), 201)


@bp.route("/job-level-targets/<target_id>", methods=["GET"])
def get_job_level_target(target_id):
    authenticate(READ_ROLES)
    return object_response(job_level_target_out(lookup.job_level_target(target_id)))


@bp.route("/job-level-targets", methods=["GET"])
def list_job_level_targets():
    authenticate(READ_ROLES)
    plan_id = query_param("plan_id")
    job_level = query_param("job_level")
    records = db.ordered(db.job_level_targets)
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if job_level is not None:
        records = [r for r in records if r["job_level"] == job_level]
    return paginated(records, job_level_target_out)

"""Registrar (abstractor) staffing endpoints."""

from flask import Blueprint

import db
import services
import spec
import validate
from db import all_of, fmt_date, mark
from middleware import ANY_ROLE, endpoint
from routes.common import PREFIX, need, ok, page

bp = Blueprint("abstractors", __name__)


@bp.post(PREFIX + "/abstractors")
@endpoint(["RegistryManager"])
def create_abstractor():
    body = validate.body()
    program_id = validate.f_str(body, "program_id")
    name = validate.f_str(body, "name")
    credential = validate.f_enum(body, "credential", spec.CREDENTIALS)
    target = validate.f_num(body, "productivity_target_cases_per_day",
                            exclusive_min=0)
    certification = validate.f_date(body, "certification_expires_on")

    need("program", program_id, "ERR_PROGRAM_NOT_FOUND")

    abstractor = db.new_entity("abstractor", {
        "program_id": program_id,
        "name": name,
        "credential": credential,
        "productivity_target_cases_per_day": target,
        "certification_expires_on": fmt_date(certification),
        "employment_status": "ACTIVE",
        "assigned_open_case_count": 0,
        "lifetime_discrepancy_points": 0,
        "audit_fail_streak": 0,
        "quality_score_rolling_90d": 100.0,
        "quality_score_cumulative": 100.0,
        "completed_cases_30d": 0,
        "productivity_rate_per_day": 0.0,
        "productivity_status": "BELOW",
    })
    return ok(abstractor, 201)


@bp.get(PREFIX + "/abstractors")
@endpoint(ANY_ROLE)
def list_abstractors():
    program_id = validate.q_str("program_id")
    credential = validate.q_enum("credential", spec.CREDENTIALS)
    employment_status = validate.q_enum("employment_status",
                                        spec.EMPLOYMENT_STATUSES)
    items = all_of("abstractor")
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if credential is not None:
        items = [a for a in items if a["credential"] == credential]
    if employment_status is not None:
        items = [a for a in items if a["employment_status"] == employment_status]
    return page(items)


@bp.get(PREFIX + "/abstractors/<abstractor_id>")
@endpoint(ANY_ROLE)
def read_abstractor(abstractor_id):
    abstractor = need("abstractor", abstractor_id, "ERR_ABSTRACTOR_NOT_FOUND")
    return ok(abstractor)


@bp.post(PREFIX + "/abstractors/<abstractor_id>/employment-status")
@endpoint(["RegistryManager"])
def set_employment_status(abstractor_id):
    body = validate.body()
    status = validate.f_enum(body, "employment_status",
                             spec.EMPLOYMENT_STATUSES)
    validate.f_date(body, "effective_on", required=False)
    validate.f_str(body, "reason", required=False)

    abstractor = need("abstractor", abstractor_id, "ERR_ABSTRACTOR_NOT_FOUND")

    mark(abstractor)
    abstractor["employment_status"] = status
    if status in ("TERMINATED", "SUSPENDED_FROM_ABSTRACTING", "LOA"):
        services.release_worklist(abstractor)
    return ok(abstractor)

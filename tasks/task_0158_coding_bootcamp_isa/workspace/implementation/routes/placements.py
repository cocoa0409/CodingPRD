"""PlacementOutcome reporting + CIRR eligibility (PRD §3.12)."""
from flask import Blueprint, request

import errors
from db import db, stamp_create
from middleware import require_role
from response import success
from services import serialize
from services.calc import cirr_eligible
from services.common import (
    get_json_body, parse_pagination, sort_by_created, paginate, lookup,
    require_fields, as_enum, as_int,
)
from services.timeutil import parse_dt

bp = Blueprint("placements", __name__)

CATEGORIES = {
    "EMPLOYED_IN_FIELD", "EMPLOYED_OUT_OF_FIELD", "SELF_EMPLOYED",
    "CONTINUED_EDUCATION", "STILL_SEEKING", "OUT_OF_PROGRAM",
}
SALARY_REQUIRED_CATEGORIES = {"EMPLOYED_IN_FIELD", "EMPLOYED_OUT_OF_FIELD"}


@bp.post("/placement-outcomes")
def create_placement():
    require_role("ComplianceOfficer")
    body = get_json_body()
    require_fields(body, ["enrollment_id", "category", "reported_at"])
    enrollment_id = body["enrollment_id"]
    if not isinstance(enrollment_id, str):
        raise errors.invalid_request("enrollment_id must be a string")
    e = lookup(db.enrollments, enrollment_id)  # existence first

    category = as_enum(body, "category", CATEGORIES)
    salary = as_int(body, "annual_salary_cents", required=False, min_value=0)
    placement_days = as_int(body, "placement_days", required=False)
    parse_dt(body["reported_at"], "reported_at")  # validate format

    # ERR_SALARY_REQUIRED (400) before ERR_OUTCOME_NOT_GRADUATE (409) per priority
    if category in SALARY_REQUIRED_CATEGORIES and salary is None:
        raise errors.ApiError(errors.ERR_SALARY_REQUIRED, 400,
                              "annual_salary_cents required for employed outcomes")
    if e["status"] != "GRADUATED":
        raise errors.ApiError(errors.ERR_OUTCOME_NOT_GRADUATE, 409,
                              "Placement outcome requires a GRADUATED enrollment")

    p = {
        "enrollment_id": enrollment_id,
        "category": category,
        "annual_salary_cents": salary,
        "placement_days": placement_days,
        "reported_at": body["reported_at"],
        "cirr_eligible": cirr_eligible(category, placement_days),
    }
    stamp_create(p)
    db.placement_outcomes[p["id"]] = p
    return success(serialize.placement_view(p), status=201)


@bp.get("/placement-outcomes/<pid>")
def get_placement(pid):
    require_role("ComplianceOfficer")
    p = lookup(db.placement_outcomes, pid)
    return success(serialize.placement_view(p))


@bp.get("/placement-outcomes")
def list_placements():
    require_role("ComplianceOfficer")
    limit, offset = parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    rows = list(db.placement_outcomes.values())
    if enrollment_id is not None:
        rows = [p for p in rows if p["enrollment_id"] == enrollment_id]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.placement_view(p) for p in window], pagination=pg)

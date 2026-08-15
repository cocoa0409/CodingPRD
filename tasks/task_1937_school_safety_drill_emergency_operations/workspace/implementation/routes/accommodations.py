"""AccommodationPlan endpoints (PRD 3.8)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized, ALL_ROLES, ROLE_OFFICER
from response import success_object
from services.core import new_record, public, apply_changes
from validate import get_body, reject_unknown, req_date, req_enum, req_str
from routes.helpers import check_site_fk, get_path, list_query

bp = Blueprint("accommodations", __name__)

NEED_TYPES = ["MOBILITY", "VISUAL", "AUDITORY", "SENSORY", "COGNITIVE"]


@bp.post("/accommodation-plans")
def create_plan():
    authorized([ROLE_OFFICER])
    body = get_body()
    check_site_fk(body)
    reject_unknown(body, ["site_id", "student_ref", "need_type",
                          "instructions", "review_by_date"])
    site_id = req_str(body, "site_id")
    student_ref = req_str(body, "student_ref")
    need_type = req_enum(body, "need_type", NEED_TYPES)
    instructions = req_str(body, "instructions")
    review_by = req_date(body, "review_by_date")

    rec = new_record("accommodation_plans", {
        "site_id": site_id,
        "student_ref": student_ref,
        "need_type": need_type,
        "instructions": instructions,
        "review_by_date": review_by,
        "status": "ACTIVE",
    })
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>/accommodation-plans")
def list_plans(rid):
    authorized(ALL_ROLES)
    get_path("sites", rid)
    filters = {
        "site_id": rid,
        "status": request.args.get("status"),
        "student_ref": request.args.get("student_ref"),
    }
    return list_query("accommodation_plans", filters)


@bp.post("/accommodation-plans/<rid>/deactivate")
def deactivate_plan(rid):
    authorized([ROLE_OFFICER])
    plan = get_path("accommodation_plans", rid)
    body = get_body()
    reject_unknown(body, [])

    if plan["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE plan may be deactivated")

    apply_changes(plan, {"status": "INACTIVE"})
    return success_object(public(plan))

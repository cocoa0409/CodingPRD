"""Advisor endpoints: POST/GET/GET/PATCH /advising/advisors[...]"""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, require_fields, stamp_new, touch,
)
from services.calculations import recompute_all_advisor_metrics

bp = Blueprint("advisors", __name__)

ROLE_READ = ("AdvisingDirector", "Advisor", "FrontDeskStaff")


def advisor_public(a):
    recompute_all_advisor_metrics(a["id"])
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "email": a["email"],
        "major_codes": a["major_codes"],
        "max_caseload": a["max_caseload"],
        "status": a["status"],
        "assigned_active_count": a["assigned_active_count"],
        "weighted_load": a["weighted_load"],
        "scheduled_minutes": a["scheduled_minutes"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/advising/advisors", methods=["POST"])
def create_advisor():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["full_name", "email", "major_codes", "max_caseload"])
    if not isinstance(data["major_codes"], list):
        raise ApiError(errors.ERR_VALIDATION, "major_codes must be an array", 400)
    if not isinstance(data["max_caseload"], int) or isinstance(data["max_caseload"], bool):
        raise ApiError(errors.ERR_VALIDATION, "max_caseload must be an integer", 400)
    if data["max_caseload"] < 1:
        raise ApiError(errors.ERR_VALIDATION, "max_caseload must be >= 1", 400)
    require_role(role, ("AdvisingDirector",))

    advisor = stamp_new({
        "full_name": data["full_name"],
        "email": data["email"],
        "major_codes": data["major_codes"],
        "max_caseload": data["max_caseload"],
        "status": "ACTIVE",
        "assigned_active_count": 0,
        "weighted_load": 0,
        "scheduled_minutes": 0,
    })
    db.advisors[advisor["id"]] = advisor
    return success_object(advisor_public(advisor), 201)


@bp.route("/advising/advisors", methods=["GET"])
def list_advisors():
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    limit, offset = get_pagination_params()
    items = list(db.advisors.values())
    status_filter = None
    from flask import request
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in ("ACTIVE", "INACTIVE"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status_filter}", 400)
        items = [a for a in items if a["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([advisor_public(a) for a in page], limit, offset, total)


@bp.route("/advising/advisors/<advisorId>", methods=["GET"])
def get_advisor(advisorId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    advisor = db.advisors.get(advisorId)
    if not advisor:
        raise ApiError(errors.ERR_ADVISOR_NOT_FOUND, f"Advisor {advisorId} not found", 404)
    return success_object(advisor_public(advisor))


@bp.route("/advising/advisors/<advisorId>", methods=["PATCH"])
def patch_advisor(advisorId):
    user_id, role = get_auth_context()
    data = body()
    # shape validation for provided fields happens before role check per pipeline
    if "status" in data and data["status"] not in ("ACTIVE", "INACTIVE"):
        raise ApiError(errors.ERR_VALIDATION, f"Invalid status: {data['status']}", 400)
    if "max_caseload" in data:
        mc = data["max_caseload"]
        if not isinstance(mc, int) or isinstance(mc, bool) or mc < 1:
            raise ApiError(errors.ERR_VALIDATION, "max_caseload must be an integer >= 1", 400)
    require_role(role, ("AdvisingDirector",))
    advisor = db.advisors.get(advisorId)
    if not advisor:
        raise ApiError(errors.ERR_ADVISOR_NOT_FOUND, f"Advisor {advisorId} not found", 404)

    recompute_all_advisor_metrics(advisorId)
    if "max_caseload" in data and data["max_caseload"] < advisor["assigned_active_count"]:
        raise ApiError(
            errors.ERR_VALIDATION,
            "max_caseload may not be set below current assigned_active_count",
            400,
        )
    if "status" in data:
        advisor["status"] = data["status"]
    if "max_caseload" in data:
        advisor["max_caseload"] = data["max_caseload"]
    touch(advisor)
    return success_object(advisor_public(advisor))

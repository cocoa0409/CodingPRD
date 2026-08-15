"""Registration hold endpoints (student sub-resource)."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, require_fields, require_enum,
    stamp_new, touch,
)
from services.calculations import (
    get_assigned_advisor_id, recompute_student_risk,
    recompute_student_requirement_and_clearance,
)

bp = Blueprint("holds", __name__)

HOLD_TYPES = ("ADVISING", "FINANCIAL", "ACADEMIC_STANDING", "ADMINISTRATIVE")


def hold_public(h):
    return {
        "id": h["id"],
        "student_id": h["student_id"],
        "hold_type": h["hold_type"],
        "requires_approved_plan": h["requires_approved_plan"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def _get_student_or_404(student_id):
    student = db.students.get(student_id)
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {student_id} not found", 404)
    return student


@bp.route("/advising/students/<id>/holds", methods=["POST"])
def create_hold(id):
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["hold_type"])
    require_enum(data["hold_type"], HOLD_TYPES, "hold_type")
    if "requires_approved_plan" in data and not isinstance(data["requires_approved_plan"], bool):
        raise ApiError(errors.ERR_VALIDATION, "requires_approved_plan must be a boolean", 400)
    require_role(role, ("AdvisingDirector",))
    student = _get_student_or_404(id)

    hold = stamp_new({
        "student_id": student["id"],
        "hold_type": data["hold_type"],
        "requires_approved_plan": data.get("requires_approved_plan", False),
        "status": "ACTIVE",
    })
    db.holds[hold["id"]] = hold
    # recompute clearance (BLOCKED) and risk (+8 per ACTIVE hold)
    recompute_student_risk(student["id"])
    return success_object(hold_public(hold), 201)


@bp.route("/advising/students/<id>/holds", methods=["GET"])
def list_holds(id):
    user_id, role = get_auth_context()
    require_role(role, ("AdvisingDirector", "Advisor", "FrontDeskStaff"))
    _get_student_or_404(id)
    limit, offset = get_pagination_params()
    items = [h for h in db.holds.values() if h["student_id"] == id]
    status = request.args.get("status")
    if status is not None:
        if status not in ("ACTIVE", "RELEASED"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status}", 400)
        items = [h for h in items if h["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([hold_public(h) for h in page], limit, offset, total)


@bp.route("/advising/students/<id>/holds/<holdId>/release", methods=["POST"])
def release_hold(id, holdId):
    user_id, role = get_auth_context()
    require_role(role, ("Advisor", "AdvisingDirector"))
    student = _get_student_or_404(id)
    hold = None
    for h in db.holds.values():
        if h["id"] == holdId and h["student_id"] == id:
            hold = h
            break
    if not hold:
        raise ApiError(errors.ERR_HOLD_NOT_FOUND,
                       f"Hold {holdId} not found under student {id}", 404)
    if hold["status"] != "ACTIVE":
        raise ApiError(errors.ERR_HOLD_NOT_ACTIVE, "Hold is not ACTIVE", 409)
    # ownership: Advisor-role caller must be the student's assigned advisor
    if role == "Advisor":
        assigned = get_assigned_advisor_id(id)
        if assigned != user_id:
            raise ApiError(errors.ERR_NOT_ASSIGNED_ADVISOR,
                           "Caller is not the student's assigned advisor", 403)
    # cross-entity: plan gate
    if hold.get("requires_approved_plan"):
        has_approved = any(
            p["student_id"] == id and p["status"] == "APPROVED"
            for p in db.degree_plans.values())
        if not has_approved:
            raise ApiError(errors.ERR_PLAN_NOT_APPROVED,
                           "Hold release requires an APPROVED degree plan", 409)

    hold["status"] = "RELEASED"
    touch(hold)
    # cascade: recompute risk (hold weight removed) then requirement/clearance
    recompute_student_risk(id)
    recompute_student_requirement_and_clearance(id)
    return success_object(hold_public(hold))

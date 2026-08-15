"""Intervention endpoints: create, list, get, close."""
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
from services.calculations import get_assigned_advisor_id, recompute_student_risk

bp = Blueprint("interventions", __name__)

ROLE_ACCESS = ("AdvisingDirector", "Advisor")
INTERVENTION_TYPES = ("ACADEMIC_COACHING", "TUTORING_REFERRAL", "COUNSELING_REFERRAL",
                      "FINANCIAL_AID_REFERRAL")


def intervention_public(i):
    return {
        "id": i["id"],
        "student_id": i["student_id"],
        "referral_id": i["referral_id"],
        "intervention_type": i["intervention_type"],
        "note": i["note"],
        "status": i["status"],
        "outcome": i["outcome"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def _check_ownership(role, user_id, student_id):
    if role == "Advisor":
        assigned = get_assigned_advisor_id(student_id)
        if assigned != user_id:
            raise ApiError(errors.ERR_NOT_ASSIGNED_ADVISOR,
                           "Caller is not the student's assigned advisor", 403)


@bp.route("/advising/interventions", methods=["POST"])
def create_intervention():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["student_id", "intervention_type"])
    require_enum(data["intervention_type"], INTERVENTION_TYPES, "intervention_type")
    require_role(role, ROLE_ACCESS)
    student = db.students.get(data["student_id"])
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {data['student_id']} not found", 404)
    referral_id = data.get("referral_id")
    if referral_id is not None and referral_id not in db.referrals:
        raise ApiError(errors.ERR_REFERRAL_NOT_FOUND, f"Referral {referral_id} not found", 404)
    _check_ownership(role, user_id, student["id"])

    intervention = stamp_new({
        "student_id": student["id"],
        "referral_id": referral_id,
        "intervention_type": data["intervention_type"],
        "note": data.get("note"),
        "status": "OPEN",
        "outcome": None,
    })
    db.interventions[intervention["id"]] = intervention
    recompute_student_risk(student["id"])
    return success_object(intervention_public(intervention), 201)


@bp.route("/advising/interventions", methods=["GET"])
def list_interventions():
    user_id, role = get_auth_context()
    require_role(role, ROLE_ACCESS)
    limit, offset = get_pagination_params()
    items = list(db.interventions.values())
    student_id = request.args.get("student_id")
    referral_id = request.args.get("referral_id")
    status = request.args.get("status")
    if student_id is not None:
        items = [i for i in items if i["student_id"] == student_id]
    if referral_id is not None:
        items = [i for i in items if i["referral_id"] == referral_id]
    if status is not None:
        if status not in ("OPEN", "CLOSED"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status}", 400)
        items = [i for i in items if i["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([intervention_public(i) for i in page], limit, offset, total)


@bp.route("/advising/interventions/<interventionId>", methods=["GET"])
def get_intervention(interventionId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_ACCESS)
    intervention = db.interventions.get(interventionId)
    if not intervention:
        raise ApiError(errors.ERR_INTERVENTION_NOT_FOUND,
                       f"Intervention {interventionId} not found", 404)
    return success_object(intervention_public(intervention))


@bp.route("/advising/interventions/<interventionId>/close", methods=["POST"])
def close_intervention(interventionId):
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["outcome"])
    require_enum(data["outcome"], ("SUCCESSFUL", "UNSUCCESSFUL"), "outcome")
    require_role(role, ROLE_ACCESS)
    intervention = db.interventions.get(interventionId)
    if not intervention:
        raise ApiError(errors.ERR_INTERVENTION_NOT_FOUND,
                       f"Intervention {interventionId} not found", 404)
    if intervention["status"] != "OPEN":
        raise ApiError(errors.ERR_INTERVENTION_ALREADY_CLOSED,
                       "Intervention is not OPEN", 409)
    _check_ownership(role, user_id, intervention["student_id"])
    intervention["status"] = "CLOSED"
    intervention["outcome"] = data["outcome"]
    touch(intervention)
    recompute_student_risk(intervention["student_id"])
    return success_object(intervention_public(intervention))

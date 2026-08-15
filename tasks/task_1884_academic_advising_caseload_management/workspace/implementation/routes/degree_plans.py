"""Degree plan endpoints (student sub-resource): create/list/get/patch/submit/approve/return."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, require_fields, stamp_new, touch,
)
from services.calculations import (
    MAX_TERM_CREDITS, compute_term_credits, get_assigned_advisor_id,
    recompute_student_requirement_and_clearance,
)

bp = Blueprint("degree_plans", __name__)

ROLE_WRITE = ("Advisor", "AdvisingDirector")
ROLE_READ = ("AdvisingDirector", "Advisor", "FrontDeskStaff")


def plan_public(p):
    per_term, total = compute_term_credits(p["terms"])
    p["mapped_credits_total"] = total
    return {
        "id": p["id"],
        "student_id": p["student_id"],
        "catalog_year": p["catalog_year"],
        "required_credits": p["required_credits"],
        "terms": p["terms"],
        "mapped_credits_total": p["mapped_credits_total"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _get_student_or_404(student_id):
    student = db.students.get(student_id)
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {student_id} not found", 404)
    return student


def _get_plan_or_404(student_id, plan_id):
    for p in db.degree_plans.values():
        if p["id"] == plan_id and p["student_id"] == student_id:
            return p
    raise ApiError(errors.ERR_PLAN_NOT_FOUND,
                   f"Plan {plan_id} not found under student {student_id}", 404)


def _check_ownership(role, user_id, student_id):
    if role == "Advisor":
        assigned = get_assigned_advisor_id(student_id)
        if assigned != user_id:
            raise ApiError(errors.ERR_NOT_ASSIGNED_ADVISOR,
                           "Caller is not the student's assigned advisor", 403)


def _validate_terms(terms):
    if not isinstance(terms, list):
        raise ApiError(errors.ERR_VALIDATION, "terms must be an array", 400)
    for term in terms:
        if not isinstance(term, dict) or "term_code" not in term or "courses" not in term:
            raise ApiError(errors.ERR_VALIDATION,
                           "Each term must have term_code and courses", 400)
        if not isinstance(term["courses"], list):
            raise ApiError(errors.ERR_VALIDATION, "courses must be an array", 400)
        for course in term["courses"]:
            if not isinstance(course, dict) or "course_code" not in course or "credits" not in course:
                raise ApiError(errors.ERR_VALIDATION,
                               "Each course must have course_code and credits", 400)
            credits = course["credits"]
            if isinstance(credits, bool) or not isinstance(credits, (int, float)):
                raise ApiError(errors.ERR_VALIDATION, "course credits must be a number", 400)


@bp.route("/advising/students/<id>/degree-plans", methods=["POST"])
def create_plan(id):
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["catalog_year", "required_credits", "terms"])
    if not isinstance(data["catalog_year"], int) or isinstance(data["catalog_year"], bool):
        raise ApiError(errors.ERR_VALIDATION, "catalog_year must be an integer", 400)
    if (not isinstance(data["required_credits"], int) or isinstance(data["required_credits"], bool)
            or data["required_credits"] < 1):
        raise ApiError(errors.ERR_VALIDATION, "required_credits must be an integer >= 1", 400)
    _validate_terms(data["terms"])
    require_role(role, ROLE_WRITE)
    _get_student_or_404(id)
    _check_ownership(role, user_id, id)

    # one non-terminal (DRAFT or SUBMITTED) plan per student
    for p in db.degree_plans.values():
        if p["student_id"] == id and p["status"] in ("DRAFT", "SUBMITTED"):
            raise ApiError(errors.ERR_PLAN_ALREADY_ACTIVE,
                           "Student already has a DRAFT or SUBMITTED degree plan", 409)

    plan = stamp_new({
        "student_id": id,
        "catalog_year": data["catalog_year"],
        "required_credits": data["required_credits"],
        "terms": data["terms"],
        "status": "DRAFT",
    })
    _, plan["mapped_credits_total"] = compute_term_credits(plan["terms"])
    db.degree_plans[plan["id"]] = plan
    return success_object(plan_public(plan), 201)


@bp.route("/advising/students/<id>/degree-plans", methods=["GET"])
def list_plans(id):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    _get_student_or_404(id)
    limit, offset = get_pagination_params()
    items = [p for p in db.degree_plans.values() if p["student_id"] == id]
    status = request.args.get("status")
    if status is not None:
        if status not in ("DRAFT", "SUBMITTED", "APPROVED"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status}", 400)
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([plan_public(p) for p in page], limit, offset, total)


@bp.route("/advising/students/<id>/degree-plans/<planId>", methods=["GET"])
def get_plan(id, planId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    _get_student_or_404(id)
    plan = _get_plan_or_404(id, planId)
    return success_object(plan_public(plan))


@bp.route("/advising/students/<id>/degree-plans/<planId>", methods=["PATCH"])
def patch_plan(id, planId):
    user_id, role = get_auth_context()
    data = body()
    if "terms" in data:
        _validate_terms(data["terms"])
    if "required_credits" in data:
        rc = data["required_credits"]
        if not isinstance(rc, int) or isinstance(rc, bool) or rc < 1:
            raise ApiError(errors.ERR_VALIDATION, "required_credits must be an integer >= 1", 400)
    require_role(role, ROLE_WRITE)
    _get_student_or_404(id)
    plan = _get_plan_or_404(id, planId)
    if plan["status"] != "DRAFT":
        raise ApiError(errors.ERR_PLAN_INVALID_STATE, "Only a DRAFT plan may be edited", 409)
    _check_ownership(role, user_id, id)

    if "terms" in data:
        plan["terms"] = data["terms"]
    if "required_credits" in data:
        plan["required_credits"] = data["required_credits"]
    _, plan["mapped_credits_total"] = compute_term_credits(plan["terms"])
    touch(plan)
    return success_object(plan_public(plan))


@bp.route("/advising/students/<id>/degree-plans/<planId>/submit", methods=["POST"])
def submit_plan(id, planId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_WRITE)
    _get_student_or_404(id)
    plan = _get_plan_or_404(id, planId)
    if plan["status"] != "DRAFT":
        raise ApiError(errors.ERR_PLAN_INVALID_STATE, "Only a DRAFT plan may be submitted", 409)
    _check_ownership(role, user_id, id)

    per_term, total = compute_term_credits(plan["terms"])
    plan["mapped_credits_total"] = total
    # gates per state machine preconditions: credits first, then overload
    if total < plan["required_credits"]:
        raise ApiError(errors.ERR_PLAN_CREDITS_INSUFFICIENT,
                       "mapped_credits_total is below required_credits", 409)
    for t in per_term:
        if t > MAX_TERM_CREDITS:
            raise ApiError(errors.ERR_PLAN_TERM_OVERLOAD,
                           f"A term's rounded credits exceed {MAX_TERM_CREDITS}", 409)
    plan["status"] = "SUBMITTED"
    touch(plan)
    return success_object(plan_public(plan))


@bp.route("/advising/students/<id>/degree-plans/<planId>/approve", methods=["POST"])
def approve_plan(id, planId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_WRITE)
    _get_student_or_404(id)
    plan = _get_plan_or_404(id, planId)
    if plan["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_PLAN_INVALID_STATE, "Only a SUBMITTED plan may be approved", 409)
    _check_ownership(role, user_id, id)
    plan["status"] = "APPROVED"
    touch(plan)
    recompute_student_requirement_and_clearance(id)
    return success_object(plan_public(plan))


@bp.route("/advising/students/<id>/degree-plans/<planId>/return", methods=["POST"])
def return_plan(id, planId):
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["reason"])
    require_role(role, ROLE_WRITE)
    _get_student_or_404(id)
    plan = _get_plan_or_404(id, planId)
    if plan["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_PLAN_INVALID_STATE, "Only a SUBMITTED plan may be returned", 409)
    _check_ownership(role, user_id, id)
    plan["status"] = "DRAFT"
    touch(plan)
    return success_object(plan_public(plan))

"""Closure plans and student transitions (PRD §3.7)."""
from flask import Blueprint

import db
import errors
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    require_non_empty_string,
    require_roles,
)
from response import success_object
from routes.common import get_or_404, paginate
from services import cascade

bp = Blueprint("closures", __name__)

OPEN_CLOSURE_STATUSES = ("INITIATED", "TRANSITION_IN_PROGRESS", "RECORDS_COMPLETE")


@bp.post("/authorizer/schools/<id>/closure-plans")
def create_closure_plan(id):
    user_id, _role = require_roles(["BoardMember"])
    school = get_or_404("schools", id)
    data = body()
    reason = require_non_empty_string(data, "reason")
    if reason not in ("REVOCATION", "VOLUNTARY"):
        # NON_RENEWAL is system-only; anything else invalid.
        raise_error(errors.ERR_INVALID_REQUEST, "reason must be REVOCATION or VOLUNTARY")
    closure_date = require_non_empty_string(data, "closure_date")
    if school["status"] != "OPEN":
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "Closure requires an OPEN school")
    for plan in db.all_records("closure_plans"):
        if plan["school_id"] == id and plan["status"] in OPEN_CLOSURE_STATUSES:
            raise_error(errors.ERR_CLOSURE_ALREADY_EXISTS, "An open closure plan already exists for the school")
    if reason == "REVOCATION":
        has_rev_review = any(
            n["school_id"] == id
            and n["level"] == "REVOCATION_REVIEW"
            and n["status"] in ("DRAFT", "ISSUED")
            for n in db.all_records("interventions")
        )
        if not has_rev_review:
            raise_error(errors.ERR_NO_REVOCATION_REVIEW_NOTICE, "REVOCATION closure requires an open REVOCATION_REVIEW notice")
    record = db.stamp_new({
        "school_id": id,
        "reason": reason,
        "closure_date": closure_date,
        "decided_by_user_id": user_id,
        "status": "INITIATED",
    })
    db.insert("closure_plans", record)
    # School OPEN -> CLOSING + lottery cascade.
    cascade.school_to_closing(school)
    if reason == "REVOCATION":
        for contract in db.all_records("contracts"):
            if contract["school_id"] == id and contract["status"] == "ACTIVE":
                contract["status"] = "REVOKED"
                db.touch(contract)
    return success_object(record, 201)


@bp.get("/authorizer/schools/<id>/closure-plans")
def list_school_closures(id):
    require_roles(ALL_ROLES)
    get_or_404("schools", id)
    records = [p for p in db.all_records("closure_plans") if p["school_id"] == id]
    return paginate(records)


@bp.get("/authorizer/closure-plans/<id>")
def get_closure_plan(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("closure_plans", id))


@bp.post("/authorizer/closure-plans/<id>/student-transitions")
def add_student_transition(id):
    require_roles(["AuthorizerStaff"])
    plan = get_or_404("closure_plans", id)
    if plan["status"] not in ("INITIATED", "TRANSITION_IN_PROGRESS"):
        raise_error(errors.ERR_CLOSURE_INVALID_STATE, "Plan is not INITIATED or TRANSITION_IN_PROGRESS")
    data = body()
    student_ref = require_non_empty_string(data, "student_ref")
    record = db.stamp_new({
        "closure_plan_id": id,
        "student_ref": student_ref,
        "destination_school": None,
        "status": "PENDING",
    })
    db.insert("student_transitions", record)
    return success_object(record, 201)


@bp.get("/authorizer/closure-plans/<id>/student-transitions")
def list_student_transitions(id):
    require_roles(ALL_ROLES)
    get_or_404("closure_plans", id)
    records = [t for t in db.all_records("student_transitions") if t["closure_plan_id"] == id]
    return paginate(records)


@bp.post("/authorizer/student-transitions/<id>/place")
def place_transition(id):
    require_roles(["AuthorizerStaff"])
    transition = get_or_404("student_transitions", id)
    if transition["status"] != "PENDING":
        raise_error(errors.ERR_TRANSITION_INVALID_STATE, "Transition is not PENDING")
    data = body()
    destination = require_non_empty_string(data, "destination_school")
    transition["status"] = "PLACED"
    transition["destination_school"] = destination
    db.touch(transition)
    return success_object(transition)


@bp.post("/authorizer/student-transitions/<id>/records-sent")
def records_sent(id):
    require_roles(["AuthorizerStaff"])
    transition = get_or_404("student_transitions", id)
    if transition["status"] != "PLACED":
        raise_error(errors.ERR_TRANSITION_INVALID_STATE, "Transition is not PLACED")
    transition["status"] = "RECORDS_SENT"
    db.touch(transition)
    return success_object(transition)


@bp.post("/authorizer/closure-plans/<id>/advance")
def advance_closure(id):
    require_roles(["AuthorizerStaff"])
    plan = get_or_404("closure_plans", id)
    status = plan["status"]
    if status == "INITIATED":
        plan["status"] = "TRANSITION_IN_PROGRESS"
        db.touch(plan)
    elif status == "TRANSITION_IN_PROGRESS":
        remaining = [
            t for t in db.all_records("student_transitions")
            if t["closure_plan_id"] == id and t["status"] in ("PENDING", "PLACED")
        ]
        if remaining:
            raise_error(errors.ERR_STUDENTS_NOT_TRANSITIONED, "Students still PENDING or PLACED")
        plan["status"] = "RECORDS_COMPLETE"
        db.touch(plan)
    elif status == "RECORDS_COMPLETE":
        plan["status"] = "CLOSED"
        db.touch(plan)
        school = db.get("schools", plan["school_id"])
        if school is not None and school["status"] == "CLOSING":
            cascade.school_to_closed(school)
    else:
        raise_error(errors.ERR_CLOSURE_INVALID_STATE, "Plan cannot be advanced from its current status")
    return success_object(plan)

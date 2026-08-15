"""Testing accommodation requests: submit, forward, approve, deny, flag."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, create_record, now, touch
from errors import (ERR_ACCOMMODATION_NOT_TEST_APPLICABLE, ERR_INVALID_STATE,
                    ERR_PLAN_NOT_ACTIVE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_TESTING_LEAD_TIME_INSUFFICIENT,
                    ERR_TESTING_REQUEST_NOT_APPROVED,
                    ERR_TESTING_REQUEST_NOT_PENDING,
                    ERR_TESTING_REQUEST_NOT_SUBMITTED, raise_err)
from middleware import body, req_str, require_roles
from response import success
from routes import list_response
from services import (MIN_LEAD_DAYS, TESTING_REVIEW_WINDOW_DAYS, emit,
                      get_accommodation, get_plan, get_testing_request,
                      posture_gate, school_of_plan, testing_out)
from util import days_between, parse_dt

bp = Blueprint("testing", __name__)

TESTING_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher", "Parent")


@bp.post("/testing-requests")
@require_roles("Section504Coordinator", "Teacher")
def create_testing_request():
    d = body()
    plan = get_plan(req_str(d, "plan_id"))
    acc = get_accommodation(req_str(d, "accommodation_id"))
    posture_gate(school_of_plan(plan))
    test_name = req_str(d, "test_name")
    test_date = parse_dt(req_str(d, "test_date"), "test_date")
    if acc["plan_id"] != plan["id"] or not acc.get("applies_to_testing", False):
        raise_err(ERR_ACCOMMODATION_NOT_TEST_APPLICABLE,
                  "Accommodation must belong to the same plan and have applies_to_testing=true")
    ts = now()
    rec = create_record(db.testing_requests, {
        "plan_id": plan["id"],
        "accommodation_id": acc["id"],
        "test_name": test_name,
        "test_date": test_date,
        "request_status": "SUBMITTED",
        "submitted_at": ts,
        "reviewed_by_staff_id": None,
        "review_deadline": ts + timedelta(days=TESTING_REVIEW_WINDOW_DAYS),
    })
    return success(testing_out(rec), 201)


@bp.get("/testing-requests")
@require_roles(*TESTING_READERS)
def list_testing_requests():
    items = list(db.testing_requests.values())
    plan_id = request.args.get("plan_id")
    acc_id = request.args.get("accommodation_id")
    status = request.args.get("request_status")
    if plan_id is not None:
        items = [t for t in items if t["plan_id"] == plan_id]
    if acc_id is not None:
        items = [t for t in items if t["accommodation_id"] == acc_id]
    if status is not None:
        items = [t for t in items if t["request_status"] == status]
    return list_response(items, testing_out)


@bp.get("/testing-requests/<requestId>")
@require_roles(*TESTING_READERS)
def get_testing_request_detail(requestId):
    return success(testing_out(get_testing_request(requestId)), 200)


@bp.post("/testing-requests/<requestId>/forward-to-district")
@require_roles("Section504Coordinator")
def forward_to_district(requestId):
    req = get_testing_request(requestId)
    plan = get_plan(req["plan_id"])
    posture_gate(school_of_plan(plan))
    if req["request_status"] != "SUBMITTED":
        raise_err(ERR_TESTING_REQUEST_NOT_SUBMITTED,
                  "Testing request must be SUBMITTED to forward")
    if plan["plan_status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to forward a testing request")
    if days_between(req["test_date"], now()) < MIN_LEAD_DAYS:
        raise_err(ERR_TESTING_LEAD_TIME_INSUFFICIENT,
                  "test_date must be at least 14 days after submission")
    req["request_status"] = "PENDING_DISTRICT_REVIEW"
    touch(req)
    return success(testing_out(req), 200)


@bp.post("/testing-requests/<requestId>/approve")
@require_roles("District504Director")
def approve_testing_request(requestId):
    req = get_testing_request(requestId)
    plan = get_plan(req["plan_id"])
    posture_gate(school_of_plan(plan))
    if req["request_status"] != "PENDING_DISTRICT_REVIEW":
        raise_err(ERR_TESTING_REQUEST_NOT_PENDING,
                  "Testing request must be PENDING_DISTRICT_REVIEW to approve")
    if plan.get("drafted_by_staff_id") == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The district reviewer must differ from the plan drafter")
    req["request_status"] = "APPROVED"
    req["reviewed_by_staff_id"] = g.user_id
    touch(req)
    return success(testing_out(req), 200)


@bp.post("/testing-requests/<requestId>/deny")
@require_roles("District504Director")
def deny_testing_request(requestId):
    req = get_testing_request(requestId)
    plan = get_plan(req["plan_id"])
    school = school_of_plan(plan)
    posture_gate(school)
    if req["request_status"] != "PENDING_DISTRICT_REVIEW":
        raise_err(ERR_TESTING_REQUEST_NOT_PENDING,
                  "Testing request must be PENDING_DISTRICT_REVIEW to deny")
    req["request_status"] = "DENIED"
    touch(req)
    emit("TEST_ACCOMM_DENIED", school["id"] if school else None, req["id"], g.user_id,
         {"plan_id": plan["id"], "test_name": req["test_name"]})
    return success(testing_out(req), 200)


@bp.post("/testing-requests/<requestId>/flag")
@require_roles("District504Director")
def flag_testing_request(requestId):
    req = get_testing_request(requestId)
    plan = get_plan(req["plan_id"])
    posture_gate(school_of_plan(plan))
    if req["request_status"] != "APPROVED":
        raise_err(ERR_TESTING_REQUEST_NOT_APPROVED,
                  "Testing request must be APPROVED to flag")
    acc = db.accommodations.get(req["accommodation_id"])
    if not (req["test_name"].startswith("State ")
            and acc is not None and acc["accommodation_status"] == "DISCONTINUED"):
        raise_err(ERR_INVALID_STATE,
                  "Flagging requires a 'State ' test whose accommodation has been DISCONTINUED")
    req["request_status"] = "FLAGGED_FOR_STATE_AUDIT"
    touch(req)
    return success(testing_out(req), 200)

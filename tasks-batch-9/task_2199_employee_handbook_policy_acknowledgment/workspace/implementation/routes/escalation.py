"""Escalation cases: the chase after a missed acknowledgment deadline."""
from flask import Blueprint

import auth
import clock
import db
import services
import validate
import web
from errors import fail

bp = Blueprint("escalation", __name__)

CASE_READ = ["HRComplianceAdmin", "PeopleManager"]


@bp.get("/escalations")
def list_cases():
    auth.authorize(CASE_READ)
    limit, offset = validate.pagination()
    rows = db.sort_created(db.all_rows("escalations"))
    rows = validate.query_filter(rows, "assignment_id")
    rows = validate.query_filter(rows, "employee_id")
    rows = validate.query_filter(rows, "notified_manager_id")
    rows = validate.query_filter(rows, "status")
    rows = validate.query_filter(rows, "tier", cast="int")
    return web.paged("escalations", rows)


@bp.get("/escalations/<escalation_case_id>")
def read_case(escalation_case_id):
    auth.authorize(CASE_READ)
    row = validate.path_row("escalations", escalation_case_id)
    return web.one("escalations", row)


@bp.post("/escalations/<escalation_case_id>/notify")
def notify_manager(escalation_case_id):
    auth.authorize(["HRComplianceAdmin"])
    case = validate.path_row("escalations", escalation_case_id)
    if case["status"] != "OPEN":
        fail("ERR_ESCALATION_INVALID_STATE", "case is %s" % case["status"])
    if case["notified_manager_id"] is None:
        fail("ERR_VALIDATION", "the subject has no manager to notify")
    case["status"] = "NOTIFIED"
    case["notice_count"] = case["notice_count"] + 1
    db.touch(case)
    return web.one("escalations", case)


@bp.post("/escalations/<escalation_case_id>/escalate-hr")
def escalate_hr(escalation_case_id):
    auth.authorize(["HRComplianceAdmin"])
    case = validate.path_row("escalations", escalation_case_id)
    if case["status"] != "NOTIFIED":
        fail("ERR_ESCALATION_INVALID_STATE", "case is %s" % case["status"])
    if case["tier"] != 3:
        fail("ERR_ESCALATION_TIER_TOO_LOW", "case tier is %s" % case["tier"])
    case["status"] = "ESCALATED_HR"
    db.touch(case)
    return web.one("escalations", case)


@bp.post("/escalations/<escalation_case_id>/close")
def close_case(escalation_case_id):
    auth.authorize(["HRComplianceAdmin"])
    case = validate.path_row("escalations", escalation_case_id)
    data = validate.body()
    validate.req_enum(data, "outcome", ["DISCIPLINARY"])
    if case["status"] != "ESCALATED_HR":
        fail("ERR_ESCALATION_INVALID_STATE", "case is %s" % case["status"])
    assignment = db.get("assignments", case["assignment_id"])
    if assignment is None or assignment["ack_state"] != "PENDING":
        fail("ERR_ASSIGNMENT_INVALID_ACK_STATE", "assignment is no longer PENDING")
    case["status"] = "CLOSED_DISCIPLINARY"
    case["closed_at"] = clock.now()
    db.touch(case)
    assignment["escalation_state"] = "RESOLVED"
    db.touch(assignment)
    employee = db.get("employees", case["employee_id"])
    if employee is not None:
        services.adjust_open_escalation(employee, -1)
    return web.one("escalations", case)

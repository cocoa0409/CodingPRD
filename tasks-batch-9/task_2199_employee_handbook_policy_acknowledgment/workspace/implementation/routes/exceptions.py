"""Policy exceptions: two-stage approval, risk scoring and expiry."""
from flask import Blueprint

import auth
import calc
import clock
import db
import services
import validate
import web
from errors import fail

bp = Blueprint("exceptions", __name__)

REASON_CODES = ["RELIGIOUS", "MEDICAL", "COLLECTIVE_BARGAINING", "ROLE_CONFLICT"]
EXCEPTION_READ = ["HRComplianceAdmin", "PeopleManager", "LegalCounsel", "Employee"]
DECISIONS = ["APPROVE", "DENY"]


def _score(row):
    version = db.get("policy_versions", row["policy_version_id"])
    document = services.document_of_version(version) if version else None
    category = document["category"] if document else None
    conservative, aggregate = calc.risk_scores(
        row["reason_code"], row["requested_days"], row["prior_exception_count"], category)
    row["risk_score_conservative"] = conservative
    row["risk_score_aggregate"] = aggregate


@bp.post("/policy-exceptions")
def create_exception():
    actor = auth.authorize(["Employee"])
    data = validate.body()
    raw_version = data.get("policy_version_id")
    if isinstance(raw_version, str):
        validate.fk("policy_versions", raw_version)
    version_id = validate.req_str(data, "policy_version_id")
    reason_code = validate.req_enum(data, "reason_code", REASON_CODES)
    justification = validate.req_str(data, "justification", max_len=2000)
    requested_days = validate.req_int(data, "requested_days", minimum=1, maximum=365)
    expected = validate.req_int(data, "expected_employee_version")
    version = validate.fk("policy_versions", version_id)
    employee = actor.entity
    if expected != employee["version"]:
        fail("ERR_STALE_EMPLOYEE_VERSION",
             "expected_employee_version %s does not match %s" % (expected, employee["version"]))
    owned = db.sort_created(services.rows_where(
        "assignments", employee_id=employee["id"], policy_version_id=version_id))
    pending = [row for row in owned if row["ack_state"] == "PENDING"]
    if owned and not pending:
        fail("ERR_ASSIGNMENT_INVALID_ACK_STATE",
             "assignment is %s" % owned[0]["ack_state"])
    if not pending:
        fail("ERR_NO_PENDING_ASSIGNMENT", "no pending assignment on that version")
    if employee["employment_status"] not in ("ACTIVE", "ON_LEAVE"):
        fail("ERR_EMPLOYEE_NOT_EMPLOYED", "requester is %s" % employee["employment_status"])
    prior = sum(1 for row in services.rows_where("policy_exceptions", employee_id=employee["id"])
                if row["status"] == "GRANTED")
    row = db.base_row()
    row.update({
        "employee_id": employee["id"],
        "policy_version_id": version["id"],
        "assignment_id": pending[0]["id"],
        "approving_manager_id": None,
        "deciding_reviewer_id": None,
        "reason_code": reason_code,
        "justification": justification,
        "requested_days": requested_days,
        "prior_exception_count": prior,
        "status": "SUBMITTED",
        "risk_score_conservative": None,
        "risk_score_aggregate": None,
        "expires_at": None,
    })
    _score(row)
    db.insert("policy_exceptions", row)
    db.touch(employee)
    return web.created("policy_exceptions", row)


@bp.get("/policy-exceptions")
def list_exceptions():
    auth.authorize(EXCEPTION_READ)
    limit, offset = validate.pagination()
    rows = db.sort_created(db.all_rows("policy_exceptions"))
    rows = validate.query_filter(rows, "employee_id")
    rows = validate.query_filter(rows, "policy_version_id")
    rows = validate.query_filter(rows, "assignment_id")
    rows = validate.query_filter(rows, "approving_manager_id")
    rows = validate.query_filter(rows, "deciding_reviewer_id")
    rows = validate.query_filter(rows, "status")
    return web.paged("policy_exceptions", rows)


@bp.get("/policy-exceptions/<policy_exception_id>")
def read_exception(policy_exception_id):
    auth.authorize(EXCEPTION_READ)
    row = validate.path_row("policy_exceptions", policy_exception_id)
    return web.one("policy_exceptions", row)


@bp.post("/policy-exceptions/<policy_exception_id>/manager-decision")
def manager_decision(policy_exception_id):
    actor = auth.authorize(["PeopleManager"])
    row = validate.path_row("policy_exceptions", policy_exception_id)
    data = validate.body()
    decision = validate.req_enum(data, "decision", DECISIONS)
    validate.opt_str(data, "note", max_len=2000)
    subject = db.get("employees", row["employee_id"])
    acting_id = actor.entity["id"] if actor.entity else None
    if subject is None or acting_id != subject["manager_id"] or acting_id == row["employee_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the acting manager may not decide this request")
    if row["status"] != "SUBMITTED":
        fail("ERR_EXCEPTION_INVALID_STATE", "request is %s" % row["status"])
    assignment = db.get("assignments", row["assignment_id"])
    if decision == "APPROVE":
        if assignment is None or assignment["ack_state"] != "PENDING":
            fail("ERR_ASSIGNMENT_INVALID_ACK_STATE", "assignment is no longer PENDING")
        row["status"] = "MANAGER_APPROVED"
    else:
        row["status"] = "DENIED"
    row["approving_manager_id"] = acting_id
    _score(row)
    db.touch(row)
    return web.one("policy_exceptions", row)


def _reviewer_conflict(reviewer_id, version_id):
    for addendum in services.rows_where("addenda", policy_version_id=version_id):
        if addendum.get("approved_by_reviewer_id") == reviewer_id:
            return True
    for review in services.rows_where("legal_reviews", policy_version_id=version_id):
        if review["status"] == "APPROVED" and review["reviewer_id"] == reviewer_id:
            return True
    return False


@bp.post("/policy-exceptions/<policy_exception_id>/legal-decision")
def legal_decision(policy_exception_id):
    actor = auth.authorize(["LegalCounsel"])
    row = validate.path_row("policy_exceptions", policy_exception_id)
    data = validate.body()
    decision = validate.req_enum(data, "decision", DECISIONS)
    validate.opt_str(data, "note", max_len=2000)
    reviewer = actor.entity
    subject = db.get("employees", row["employee_id"])
    if subject is None or reviewer["jurisdiction_id"] != subject["jurisdiction_id"]:
        fail("ERR_REVIEWER_JURISDICTION_MISMATCH",
             "counsel is not seated in the requester's jurisdiction")
    if decision == "APPROVE" and _reviewer_conflict(reviewer["id"], row["policy_version_id"]):
        fail("ERR_SOD_REVIEWER_CONFLICT", "counsel certified this policy version")
    if row["status"] != "MANAGER_APPROVED":
        fail("ERR_EXCEPTION_INVALID_STATE", "request is %s" % row["status"])
    if decision == "APPROVE":
        if row["risk_score_conservative"] >= calc.GRANT_RISK_CEILING:
            fail("ERR_EXCEPTION_RISK_TOO_HIGH",
                 "conservative risk score is %s" % row["risk_score_conservative"])
        row["status"] = "GRANTED"
        row["deciding_reviewer_id"] = reviewer["id"]
        row["expires_at"] = clock.add_days(clock.now(), row["requested_days"])
        assignment = db.get("assignments", row["assignment_id"])
        if assignment is not None and assignment["ack_state"] == "PENDING":
            assignment["ack_state"] = "EXEMPT"
            db.touch(assignment)
            employee = services.employee_of(assignment)
            if employee is not None:
                services.adjust_open_ack(employee, -1)
            services.close_cases_for_assignment(assignment, "CLOSED_MOOT", "MOOT")
            package = db.get("release_packages", assignment["release_package_id"])
            if package is not None:
                services.maybe_close_package(package)
    else:
        row["status"] = "DENIED"
        row["deciding_reviewer_id"] = reviewer["id"]
    db.touch(row)
    return web.one("policy_exceptions", row)


@bp.post("/policy-exceptions/<policy_exception_id>/revoke")
def revoke_exception(policy_exception_id):
    auth.authorize(["HRComplianceAdmin"])
    row = validate.path_row("policy_exceptions", policy_exception_id)
    data = validate.body()
    validate.opt_str(data, "reason")
    if row["status"] != "GRANTED":
        fail("ERR_EXCEPTION_INVALID_STATE", "request is %s" % row["status"])
    row["status"] = "REVOKED"
    db.touch(row)
    assignment = db.get("assignments", row["assignment_id"])
    if assignment is not None and assignment["ack_state"] == "EXEMPT":
        assignment["ack_state"] = "PENDING"
        db.touch(assignment)
        employee = services.employee_of(assignment)
        if employee is not None:
            services.adjust_open_ack(employee, 1)
        services.reopen_package(assignment)
    return web.one("policy_exceptions", row)

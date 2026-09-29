"""Distribution assignments, acknowledgment evidence and retention rows."""
from flask import Blueprint, request

import auth
import calc
import clock
import db
import services
import validate
import web
from errors import fail

bp = Blueprint("distribution", __name__)


@bp.get("/assignments")
def list_assignments():
    auth.authorize(["HRComplianceAdmin", "PeopleManager", "Employee", "PolicyAuthor"])
    limit, offset = validate.pagination()
    rows = db.sort_created(db.all_rows("assignments"))
    rows = validate.query_filter(rows, "release_package_id")
    rows = validate.query_filter(rows, "policy_version_id")
    rows = validate.query_filter(rows, "employee_id")
    rows = validate.query_filter(rows, "jurisdiction_id")
    rows = validate.query_filter(rows, "ack_state")
    rows = validate.query_filter(rows, "escalation_state")
    return web.paged("assignments", rows)


@bp.get("/assignments/<assignment_id>")
def read_assignment(assignment_id):
    auth.authorize(["HRComplianceAdmin", "PeopleManager", "Employee"])
    row = validate.path_row("assignments", assignment_id)
    return web.one("assignments", row)


def _rendition_for_delivery(assignment, employee):
    track = services.published_translation(assignment["policy_version_id"],
                                           employee["preferred_language_code"])
    if track is None:
        fail("ERR_ACCESSIBLE_RENDITION_UNAVAILABLE",
             "no published %s rendition" % employee["preferred_language_code"])
    if employee["needs_accessible_format"]:
        index = track.get("a11y_index")
        if index is None or index < calc.A11Y_AAA_MIN:
            fail("ERR_ACCESSIBLE_RENDITION_UNAVAILABLE",
                 "rendition does not clear the accessibility floor")
    return track


@bp.post("/assignments/<assignment_id>/deliver")
def deliver(assignment_id):
    auth.authorize(["HRComplianceAdmin"])
    assignment = validate.path_row("assignments", assignment_id)
    if assignment["ack_state"] != "UNDELIVERED":
        fail("ERR_ASSIGNMENT_INVALID_ACK_STATE", "assignment is %s" % assignment["ack_state"])
    employee = services.employee_of(assignment)
    if employee["employment_status"] not in ("ACTIVE", "ON_LEAVE"):
        fail("ERR_EMPLOYEE_NOT_EMPLOYED", "assignee is %s" % employee["employment_status"])
    _rendition_for_delivery(assignment, employee)
    assignment["ack_state"] = "PENDING"
    assignment["delivered_at"] = clock.now()
    db.touch(assignment)
    return web.one("assignments", assignment)


ACK_METHODS = ["ESIGN", "WET_SIGNATURE", "ATTESTED"]


@bp.post("/acknowledgments")
def create_acknowledgment():
    actor = auth.authorize(["Employee", "HRComplianceAdmin"])
    data = validate.body()
    raw_assignment = data.get("assignment_id")
    if isinstance(raw_assignment, str):
        validate.fk("assignments", raw_assignment)
    assignment_id = validate.req_str(data, "assignment_id")
    method = validate.req_enum(data, "method", ACK_METHODS)
    language_code = validate.req_lang(data, "language_code")
    signature_text = validate.req_str(data, "signature_text")
    assignment = validate.fk("assignments", assignment_id)
    if actor.role == "Employee":
        if actor.entity is None or actor.entity["id"] != assignment["employee_id"]:
            fail("ERR_NOT_ASSIGNMENT_OWNER", "employee is not the assignee")
    elif method != "ATTESTED":
        fail("ERR_NOT_ASSIGNMENT_OWNER",
             "an administrator may only record an ATTESTED proxy acknowledgment")
    if assignment["ack_state"] != "PENDING":
        fail("ERR_ASSIGNMENT_INVALID_ACK_STATE", "assignment is %s" % assignment["ack_state"])
    employee = services.employee_of(assignment)
    if employee["employment_status"] not in ("ACTIVE", "ON_LEAVE"):
        fail("ERR_EMPLOYEE_NOT_EMPLOYED", "assignee is %s" % employee["employment_status"])
    jurisdiction = db.get("jurisdictions", assignment["jurisdiction_id"])
    if method == "ESIGN" and not (jurisdiction and jurisdiction["esign_permitted"]):
        fail("ERR_ESIGN_NOT_PERMITTED", "electronic signature is not permitted here")
    if method == "ATTESTED":
        if not (jurisdiction and jurisdiction["proxy_ack_permitted"]) \
                or actor.role != "HRComplianceAdmin":
            fail("ERR_PROXY_ACK_NOT_PERMITTED", "proxy acknowledgment is not permitted here")
    if services.published_translation(assignment["policy_version_id"], language_code) is None:
        fail("ERR_RENDITION_LANGUAGE_UNKNOWN", "no published %s rendition" % language_code)
    captured_at = clock.now()
    row = db.base_row(versioned=False)
    row.update({
        "assignment_id": assignment["id"],
        "employee_id": assignment["employee_id"],
        "method": method,
        "language_code": language_code,
        "signature_text": signature_text,
        "captured_at": captured_at,
        "status": "EFFECTIVE",
        "revoked_at": None,
    })
    db.insert("acknowledgments", row)
    assignment["ack_state"] = "ACKNOWLEDGED"
    assignment["acknowledged_at"] = captured_at
    db.touch(assignment)
    services.append_retention(row, assignment, "CAPTURE", 1)
    services.adjust_open_ack(employee, -1)
    services.close_cases_for_assignment(assignment, "CLOSED_ACKNOWLEDGED", "RESOLVED")
    package = db.get("release_packages", assignment["release_package_id"])
    if package is not None:
        services.maybe_close_package(package)
    return web.created("acknowledgments", row)


@bp.get("/acknowledgments")
def list_acknowledgments():
    auth.authorize(["HRComplianceAdmin", "Employee", "PeopleManager"])
    limit, offset = validate.pagination()
    rows = db.sort_created(db.all_rows("acknowledgments"))
    rows = validate.query_filter(rows, "assignment_id")
    rows = validate.query_filter(rows, "employee_id")
    rows = validate.query_filter(rows, "status")
    return web.paged("acknowledgments", rows)


@bp.get("/acknowledgments/<acknowledgment_id>")
def read_acknowledgment(acknowledgment_id):
    auth.authorize(["HRComplianceAdmin", "Employee", "PeopleManager"])
    row = validate.path_row("acknowledgments", acknowledgment_id)
    return web.one("acknowledgments", row)


@bp.post("/acknowledgments/<acknowledgment_id>/revoke")
def revoke_acknowledgment(acknowledgment_id):
    auth.authorize(["HRComplianceAdmin"])
    row = validate.path_row("acknowledgments", acknowledgment_id)
    data = validate.body()
    validate.opt_str(data, "reason")
    assignment = db.get("assignments", row["assignment_id"])
    if row["status"] != "EFFECTIVE":
        fail("ERR_ASSIGNMENT_INVALID_ACK_STATE", "acknowledgment is %s" % row["status"])
    if assignment is None or assignment["ack_state"] != "ACKNOWLEDGED":
        fail("ERR_ASSIGNMENT_INVALID_ACK_STATE", "assignment is not ACKNOWLEDGED")
    row["status"] = "REVOKED"
    row["revoked_at"] = clock.now()
    services.append_retention(row, assignment, "REVOCATION", -1)
    assignment["ack_state"] = "PENDING"
    assignment["acknowledged_at"] = None
    db.touch(assignment)
    employee = services.employee_of(assignment)
    if employee is not None:
        services.adjust_open_ack(employee, 1)
    services.reopen_package(assignment)
    return web.one("acknowledgments", row)


@bp.get("/retention-records")
def list_retention():
    auth.authorize(["HRComplianceAdmin"])
    limit, offset = validate.pagination()
    rows = db.sort_created(db.all_rows("retention_records"))
    rows = validate.query_filter(rows, "acknowledgment_id")
    rows = validate.query_filter(rows, "employee_id")
    rows = validate.query_filter(rows, "jurisdiction_id")
    rows = validate.query_filter(rows, "legal_hold", cast="bool")
    return web.paged("retention_records", rows)


@bp.get("/retention-records/<retention_record_id>")
def read_retention(retention_record_id):
    auth.authorize(["HRComplianceAdmin"])
    row = validate.path_row("retention_records", retention_record_id)
    return web.one("retention_records", row)


@bp.post("/retention-records/<retention_record_id>/legal-hold")
def place_legal_hold(retention_record_id):
    auth.authorize(["HRComplianceAdmin"])
    row = validate.path_row("retention_records", retention_record_id)
    data = validate.body()
    hold_reason = validate.req_str(data, "hold_reason")
    row["legal_hold"] = True
    row["hold_reason"] = hold_reason
    return web.one("retention_records", row)

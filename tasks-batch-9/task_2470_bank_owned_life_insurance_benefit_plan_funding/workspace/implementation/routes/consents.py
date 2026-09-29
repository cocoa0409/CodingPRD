"""Notice-and-consent documentation (PRD 3.2)."""

from flask import Blueprint

import calc
from errors import ApiError
from response import collection_response, resource_response
from store import create_record, db, touch
from validation import (
    authorize,
    find_consent,
    find_employee,
    get_datetime,
    get_id,
    get_string,
    guard_terminal,
    guard_transition,
    json_body,
    pagination,
    query_enum,
    query_str,
)

bp = Blueprint("consents", __name__)

CONSENT_STATUSES = ("DRAFT", "EXECUTED", "REVOKED", "EXPIRED")
TERMINAL = ("REVOKED", "EXPIRED")
READ_ROLES = ("BenefitsAnalyst", "RiskOfficer", "ClaimsAdministrator")


@bp.post("/consent-records")
def create_consent():
    authorize(("BenefitsAnalyst",))
    body = json_body()
    employee_id = get_id(body, "employee_id")
    raw_start, start = get_datetime(body, "coverage_start_date")
    raw_end, end = get_datetime(body, "coverage_end_date")
    consent_form_reference = get_string(body, "consent_form_reference")
    notice_and_consent_version = get_string(body, "notice_and_consent_version")

    find_employee(employee_id)
    if calc.consent_window_conflicts(employee_id, start, end):
        raise ApiError("ERR_CONSENT_WINDOW_OVERLAP")

    record = create_record(
        db.consent_records,
        {
            "employee_id": employee_id,
            "coverage_start_date": raw_start,
            "_coverage_start_date": start,
            "coverage_end_date": raw_end,
            "_coverage_end_date": end,
            "consent_form_reference": consent_form_reference,
            "notice_and_consent_version": notice_and_consent_version,
            "status": "DRAFT",
            "executed_at": None,
        },
    )
    return resource_response(record, 201)


@bp.get("/consent-records")
def list_consents():
    authorize(READ_ROLES)
    limit, offset = pagination()
    employee_id = query_str("employee_id")
    status = query_enum("status", CONSENT_STATUSES)
    rows = []
    for record in db.consent_records.values():
        if employee_id is not None and record["employee_id"] != employee_id:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    return collection_response(rows, limit, offset)


@bp.get("/consent-records/<record_id>")
def read_consent(record_id):
    authorize(READ_ROLES)
    return resource_response(find_consent(record_id))


@bp.post("/consent-records/<record_id>/execute")
def execute_consent(record_id):
    authorize(("BenefitsAnalyst",))
    record = find_consent(record_id)
    guard_terminal(record["status"], TERMINAL)
    guard_transition(record["status"] == "DRAFT")
    employee = db.employees.get(record["employee_id"])
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    guard_transition(employee["employment_status"] == "ACTIVE")
    if db.now() > record["_coverage_end_date"]:
        raise ApiError("ERR_CONSENT_EXPIRED")

    record["status"] = "EXECUTED"
    record["executed_at"] = db.now()
    touch(record)

    employee["insurable_interest_status"] = calc.derive_insurable_interest(employee)
    touch(employee)
    return resource_response(record)


@bp.post("/consent-records/<record_id>/revoke")
def revoke_consent(record_id):
    authorize(("BenefitsAnalyst",))
    record = find_consent(record_id)
    guard_terminal(record["status"], TERMINAL)
    guard_transition(record["status"] == "EXECUTED")
    record["status"] = "REVOKED"
    touch(record)

    employee = db.employees.get(record["employee_id"])
    if employee is not None:
        remaining = any(
            other["employee_id"] == employee["id"] and other["status"] == "EXECUTED"
            for other in db.consent_records.values()
        )
        if not remaining:
            employee["insurable_interest_status"] = "NOT_ESTABLISHED"
            touch(employee)
    return resource_response(record)

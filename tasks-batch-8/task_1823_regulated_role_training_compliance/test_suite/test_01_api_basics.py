"""API basics: response envelope, schema validation, existence, config defaults."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_regulator,
    create_regulator,
    create_role,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories

ADMIN = TEST_USERS["compliance_admin_headers"]
HR = TEST_USERS["hr_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_success_and_error_envelope_shapes(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error." and "The `message` provides a human-readable explanation
    of what went wrong."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    reg = create_regulator(code="REG-ENV", name="ENV Regulator", recordkeeping_years=5)

    ok = api.get_regulator(reg["id"], AUDITOR)
    assert ok.status_code == 200
    body = ok.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["code"] == "REG-ENV"

    err = api.get_regulator("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", AUDITOR)
    err_body = err.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()


def test_get_assignment_with_nonexistent_id_returns_404(api):
    """PRD §2.8: "the system validates the existence of each identifier in
    sequential, left-to-right order, rejecting the request immediately with
    `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not correspond
    to an existing resource."

    Design: Corner/entities/assignment_get_not_found_returns_404
    """
    resp = api.get_assignment("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_employee_create_missing_employee_no_rejected(api):
    """PRD §3.3: "An **Employee** is registered by an `HRAdmin` with a unique
    `employee_no`, a `full_name`, a `hired_at` timestamp (recorded for the file,
    never clock-gated against the logical clock), a `current_role_id`, and an
    optional `manager_id` referencing another employee as direct manager — the
    field is nullable, since someone sits at the top of the tree."
    PRD §2.9: "**Request-body schema** — required fields present, types valid,
    enum membership respected, ranges enforced (scores between 0 and 100, day
    counts within their stated ranges), and a leave's `end_date` no earlier than
    its `start_date` (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/employee_create_missing_required_field_returns_invalid_request
    """
    role = create_role(code="R-MRF", name="MRF Role")
    payload = {
        "full_name": "No Number",
        "hired_at": "2026-08-03T09:00:00Z",
        "current_role_id": role["id"],
    }
    resp = api.create_employee(payload, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    lst = api.list_employees(ADMIN, params={})
    _, meta = validate_paginated(lst)
    assert meta["total_count"] == 0, "rejected create must not persist an employee"


def test_regulator_create_with_invalid_deadline_mode_rejected(api):
    """PRD §3.1: "a `deadline_mode` of either `CALENDAR` or `BUSINESS_DAYS`"
    PRD §2.9: "**Request-body schema** — required fields present, types valid,
    enum membership respected, ranges enforced (scores between 0 and 100, day
    counts within their stated ranges), and a leave's `end_date` no earlier than
    its `start_date` (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/regulator_create_with_invalid_enum_deadline_mode
    """
    payload = factories.create_regulator_payload(
        code="REG-BAD", name="Bad", deadline_mode="WEEKLY", recordkeeping_years=5,
    )
    resp = api.create_regulator(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_regulator_creation_applies_escalation_defaults(api):
    """PRD §3.1: "Two optional knobs tune the escalation ladder:
    `escalation_interval_days`, defaulting to 10 and bounded between 1 and 90,
    sets how many days past due a SOFT-criticality assignment may sit before it
    escalates to the compliance office; `reminder_days_before_due`, defaulting
    to 7 and bounded between 0 and 30, sets how far ahead of the due date an
    assignment is flagged as due soon. A regulator is born with `status` `ACTIVE`."

    Design: Corner/entities/regulator_creation_applies_escalation_defaults
    """
    payload = factories.create_regulator_payload(
        code="REG-DEF", name="Defaults Regulator", deadline_mode="CALENDAR",
        recordkeeping_years=5,
    )
    resp = api.create_regulator(payload, ADMIN)
    data = validate_success(resp, 201)
    assert_regulator(data)
    assert data["escalation_interval_days"] == 10, "default escalation interval is 10"
    assert data["reminder_days_before_due"] == 7, "default reminder window is 7"
    assert data["status"] == "ACTIVE"

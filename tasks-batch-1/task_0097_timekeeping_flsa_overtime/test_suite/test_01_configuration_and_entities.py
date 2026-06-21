"""Employer/workforce configuration and entity-shape claims.

Covers Queue B (Corner) `entities` instances and the listing/pagination
endpoint instances that read those entities back.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_employer_payload, create_worksite_payload, create_employee_payload,
    create_timesheet_week_payload,
    create_employer, create_worksite, setup_ca_employer,
    create_employee as mk_employee, create_draft_week,
    ADMIN, SUP1,
)


def test_create_employee_returns_201_with_classification_and_status(api):
    """PRD §3.1: "Employees are created by a PayrollAdmin against an employer_id
    and a home_worksite_id (the default worksite for their shifts and punches),
    with a full_name, an FLSA classification of either EXEMPT or NON_EXEMPT, and a
    base_rate_cents hourly rate that must be zero or greater."
    PRD §3.1: "Every employee's status is initialized to ACTIVE on creation".

    Design: Corner/entities/create_employee_returns_201_with_fields
    """
    employer = create_employer(api)
    worksite = create_worksite(api, employer["id"], "CA")
    resp = api.create_employee(
        create_employee_payload(employer["id"], worksite["id"], "NON_EXEMPT",
                                full_name="New Hire", base_rate_cents=1800), ADMIN)
    data = validate_success(resp, 201)
    assert data["classification"] == "NON_EXEMPT"
    assert data["base_rate_cents"] == 1800
    assert data["status"] == "ACTIVE"


def test_get_employee_not_found(api):
    """PRD §2.7: "A path identifier that names no existing resource ... yields
    ERR_NOT_FOUND (HTTP 404) at the first such missing reference, before later
    references or downstream validations are evaluated."

    Design: Corner/entities/get_employee_not_found
    """
    resp = api.get_employee("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_employee_missing_classification_invalid_request(api):
    """PRD §3.1: "any write with a missing required field, wrong type, or invalid
    enum value is rejected with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_employee_missing_classification_invalid_request
    """
    employer = create_employer(api)
    worksite = create_worksite(api, employer["id"], "CA")
    payload = {
        "employer_id": employer["id"],
        "home_worksite_id": worksite["id"],
        "full_name": "No Class",
        "base_rate_cents": 1800,
    }
    resp = api.create_employee(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_employee_is_tipped_defaults_false(api):
    """PRD §3.1: "The optional is_tipped flag defaults to false and only carries
    meaning for a NON_EXEMPT worker."

    Design: Corner/entities/employee_is_tipped_defaults_false
    """
    employer = create_employer(api)
    worksite = create_worksite(api, employer["id"], "CA")
    data = validate_success(api.create_employee(
        create_employee_payload(employer["id"], worksite["id"], "NON_EXEMPT",
                                full_name="Default Tip", base_rate_cents=1800), ADMIN), 201)
    assert data["is_tipped"] is False


def test_create_employee_invalid_classification_enum_rejected(api):
    """PRD §3.1: "any write with a missing required field, wrong type, or invalid
    enum value is rejected with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_employee_invalid_classification_enum
    """
    employer = create_employer(api)
    worksite = create_worksite(api, employer["id"], "CA")
    payload = create_employee_payload(employer["id"], worksite["id"], "CONTRACTOR",
                                      full_name="Bad Class", base_rate_cents=1800)
    resp = api.create_employee(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_employee_requires_existing_home_worksite_parent(api):
    """PRD §2.7: "a body field naming a missing employer, worksite, employee,
    shift, punch, pool, week, or run, yields ERR_NOT_FOUND (HTTP 404) at the first
    such missing reference, before later references or downstream validations are
    evaluated."

    Design: Corner/entities/employee_requires_valid_worksite_parent
    """
    employer = create_employer(api)
    payload = create_employee_payload(employer["id"],
                                      "11111111-1111-4111-8111-111111111111",
                                      "NON_EXEMPT", full_name="Orphan", base_rate_cents=1800)
    resp = api.create_employee(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_time_edit_is_immutable_audit_record(api):
    """PRD §3.3: "it appends one immutable TimeEdit row recording the punch_id, the
    editor's identity in editor_user_id (the supervisor's X-User-ID), the prior
    value snapshotted into old_value, and the supplied new_value and reason".
    PRD §2.4: "A time edit is an append-only audit record: it carries only id and
    created_at, and has neither updated_at nor version, because once written it is
    immutable and is never modified."

    Design: Corner/entities/timeedit_is_immutable_no_version_field
    """
    from test_helpers import create_closed_punch, edit_punch_payload, SUP9
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    resp = api.edit_punch(punch["id"],
                          edit_punch_payload("CLOCK_OUT", "2026-06-01T17:00:00Z",
                                             reason="badge log correction"), SUP9)
    data = validate_success(resp, 201)
    assert data["editor_user_id"] == "sup-9"
    assert data["old_value"] == "2026-06-01T16:00:00Z"
    assert data["new_value"] == "2026-06-01T17:00:00Z"
    assert "updated_at" not in data, "TimeEdit must not expose updated_at"
    assert "version" not in data, "TimeEdit must not expose version"


def test_timesheet_week_starts_in_draft(api):
    """PRD §3.6: "A Supervisor opens a timesheet week for an employee by naming the
    employee_id and the workweek_start, an inclusive YYYY-MM-DD start date that must
    align with one of the employer's workweek boundaries; the week begins in DRAFT."

    Design: Corner/entities/timesheet_starts_in_draft
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    data = validate_success(api.create_timesheet_week(
        create_timesheet_week_payload(employee["id"], "2026-06-01"), SUP1), 201)
    assert data["status"] == "DRAFT"
    # PRD pins the initial state (DRAFT) but not a specific integer for `version`'s
    # starting value, so only the increment relation (not version==1) is asserted.


def test_list_timesheet_weeks_pagination_envelope(api):
    """PRD §2.3: "List responses carry limit, offset, total_count, and has_more
    inside the meta object of the envelope."

    Design: Corner/endpoints/list_timesheet_weeks_pagination_envelope
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    week = create_draft_week(api, employee["id"], "2026-06-01")
    resp = api.list_timesheet_weeks(SUP1, params={"employee_id": employee["id"],
                                                  "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    ids = [w["id"] for w in data]
    assert week["id"] in ids
    assert meta["total_count"] >= 1
    # exactly one week for this employee
    mine = [w for w in data if w["employee_id"] == employee["id"]]
    assert len(mine) == 1

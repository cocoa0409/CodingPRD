"""RBAC, ownership, error envelope, and optimistic concurrency (PRD §2.1, §2.2, §2.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_call_with_fresh_version,
    api_client,
    create_employee,
    create_job,
    get_job,
    issue_call,
    make_employee_headers,
    set_clock,
    setup_board_with_employees,
    setup_tied_up_assignment,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]
CALLER = TEST_USERS["crew_caller_headers"]


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing either header, presenting a blank value, or
    naming an undeclared role is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    resp = api_client.list_employees(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_employee_cannot_issue_calls(api):
    """PRD §2.1: "A request whose role is syntactically valid but not listed
    among the endpoint's permitted roles is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403) — a craft employee issuing a call or a
    caller finalizing pay are canonical examples."

    Design: Corner/rbac/employee_cannot_issue_calls
    """
    set_clock()
    emp = create_employee()
    job = create_job()
    resp = api_client.issue_call(job["id"], make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_crewcaller_cannot_finalize_pay(api):
    """PRD §2.1: "A request whose role is syntactically valid but not listed
    among the endpoint's permitted roles is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403) — a craft employee issuing a call or a
    caller finalizing pay are canonical examples."

    Design: Corner/rbac/crewcaller_cannot_finalize_pay
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=240,
                                   report_time="2026-08-02T06:00:00Z")
    emp_id = ctx["employee"]["id"]
    resp = api_client.submit_pay_record(
        ctx["pay_record"]["id"], make_employee_headers(emp_id)
    )
    submitted = validate_success(resp)

    resp = api_client.finalize_pay_record(
        ctx["pay_record"]["id"],
        {"expected_pay_record_version": submitted["version"]},
        CALLER,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_ownership_check_employee_cannot_mark_up_another(api):
    """PRD §2.1: "When the header identity does not match the employee the
    operation targets, the request is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."

    Design: Corner/validations/ownership_check_employee_cannot_mark_up_another
    """
    set_clock()
    e1 = create_employee(full_name="Owner Olga")
    e2 = create_employee(full_name="Owner Owen")
    resp = api_client.lay_off_employee(e2["id"], make_employee_headers(e1["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format:" with `response_type` fixed to "error".
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api_client.get_job(NON_EXISTENT_UUID, MANAGER)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error", (
        f"error responses must carry response_type 'error', got {body.get('response_type')}"
    )
    assert isinstance(error_data["message"], str) and error_data["message"], (
        "error responses must carry a non-empty human-readable message"
    )


def test_occ_stale_pay_version_rejected(api):
    """PRD §2.8: "Finalizing a pay record requires the request to carry
    `expected_pay_record_version`, the record `version` the manager last
    observed. If the record's current `version` has advanced — for example
    because the employee just resubmitted the claim, legitimately recomputing
    `gross_pay_cents` under the provisional variant — the finalization is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_pay_version_rejected
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=240,
                                   report_time="2026-08-02T06:00:00Z")
    emp_id = ctx["employee"]["id"]
    pay_id = ctx["pay_record"]["id"]

    resp = api_client.submit_pay_record(pay_id, make_employee_headers(emp_id))
    submitted = validate_success(resp)
    stale_version = submitted["version"]

    api_client.dispute_pay_record(pay_id, MANAGER)
    resp = api_client.resubmit_pay_record(
        pay_id, {"claimed_minutes": 240}, make_employee_headers(emp_id)
    )
    current = validate_success(resp)
    current_version = current["version"]
    assert current_version != stale_version

    resp = api_client.finalize_pay_record(
        pay_id, {"expected_pay_record_version": stale_version}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    resp = api_client.finalize_pay_record(
        pay_id, {"expected_pay_record_version": current_version}, MANAGER
    )
    data = validate_success(resp)
    assert data["record_status"] == "FINALIZED"


def test_occ_stale_job_version_on_accept(api):
    """PRD §2.8: "Accepting a call requires the request to carry
    `expected_job_version`, the job `version` the employee last observed. If the
    job's current `version` has advanced — for example because another crew seat
    was just filled and `filled_count` moved — the acceptance is rejected with
    `ERR_STALE_VERSION` (HTTP 412), since the employee's view of the remaining
    seats is stale."
    PRD §3.4: "The job's `filled_count` increments by one — a mutation that also
    advances the job's `version` and refreshes `updated_at` — and when
    `filled_count` reaches `crew_required` the job transitions from `CALLING` to
    `FILLED`."

    Design: Corner/complexity_layers/occ_stale_job_version_on_accept
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    e1, e2 = (e["id"] for e in ctx["employees"])
    job = create_job(report_time="2026-08-03T08:00:00Z", crew_required=2)
    stale_version = job["version"]

    call1 = issue_call(job["id"])
    resp = accept_call_with_fresh_version(call1["id"], e1)
    validate_success(resp, expected_status=201)

    call2 = issue_call(job["id"])
    assert call2["employee_id"] == e2

    # The first accept bumped the job version (filled_count 0 -> 1), so the
    # creation-time version is now stale.
    resp = api_client.accept_call(
        call2["id"], {"expected_job_version": stale_version},
        make_employee_headers(e2),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    resp = accept_call_with_fresh_version(call2["id"], e2)
    assignment = validate_success(resp, expected_status=201)
    assert assignment["assignment_status"] == "MARKED_UP"
    assert get_job(job["id"])["filled_count"] == 2

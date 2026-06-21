"""Employee termination cascade, eligibility gating on activation, and the
empty-cascade edge of terminating an employee with no active coverage.

Covers Difficulty/transitive_cascade (terminate), Difficulty/boundary_precision_check
(empty terminate), and Difficulty/cross_entity_state_dependency (activate eligibility).
"""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId,
    setup_active_medical_enrollment, setup_eligible_employee,
    create_offering, create_tier, create_draft_enrollment, employee_version,
    list_carrier_feed_records,
    api_client as api,
    TEST_USERS,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]


def test_terminate_employee_supersedes_active_enrollment():
    """PRD §3.1: "Every enrollment of that employee currently in the ACTIVE state
    transitions to SUPERSEDED with its coverage_end_date set to the current clock date,
    and each such superseded enrollment in turn emits a carrier feed record carrying the
    TERM transaction maintenance type."

    Design: Difficulty/transitive_cascade/terminate_employee_supersede_term_feed_chain
    """
    ctx = setup_active_medical_enrollment()
    emp_id = ctx["employee"]["id"]
    enr_id = ctx["enrollment"]["id"]
    emp = get_success_data(api.terminate_employee(emp_id, _ADMIN))
    assert emp["eligibility_status"] == "TERMINATED", emp
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "SUPERSEDED", enr


def test_terminate_employee_emits_single_term_feed_record():
    """PRD §3.1: "each such superseded enrollment in turn emits a carrier feed record
    carrying the TERM transaction maintenance type."

    Design: Difficulty/transitive_cascade/terminate_employee_supersede_term_feed_chain
    """
    ctx = setup_active_medical_enrollment()
    emp_id = ctx["employee"]["id"]
    enr_id = ctx["enrollment"]["id"]
    get_success_data(api.terminate_employee(emp_id, _ADMIN))
    term, _ = list_carrier_feed_records(enrollment_id=enr_id, transaction_set="TERM")
    assert len(term) == 1, term


def test_terminate_employee_with_no_active_enrollments_succeeds():
    """PRD §3.1: "Termination is permitted only when the employee's eligibility_status is
    ELIGIBLE; it moves the employee to TERMINATED and cascades through the employee's
    coverage. Every enrollment of that employee currently in the ACTIVE state transitions
    to SUPERSEDED".

    Design: Difficulty/boundary_precision_check/terminate_employee_with_zero_active_enrollments_empty_set
    """
    emp = setup_eligible_employee()
    terminated = get_success_data(api.terminate_employee(emp["id"], _ADMIN))
    assert terminated["eligibility_status"] == "TERMINATED", terminated
    records = get_success_data(api.list_carrier_feed_records(
        _ADMIN, params={"employee_id": emp["id"]}))
    assert len(records) == 0, records


def test_terminate_employee_with_no_coverage_emits_no_feed_records():
    """PRD §3.1: "each such superseded enrollment in turn emits a carrier feed record
    carrying the TERM transaction maintenance type."

    Design: Difficulty/boundary_precision_check/terminate_employee_with_zero_active_enrollments_empty_set
    """
    emp = setup_eligible_employee()
    get_success_data(api.terminate_employee(emp["id"], _ADMIN))
    records = get_success_data(api.list_carrier_feed_records(
        _ADMIN, params={"employee_id": emp["id"]}))
    assert records == [], records


def test_activate_enrollment_requires_employee_eligible():
    """PRD §3.4: "the owning employee's eligibility_status must be ELIGIBLE, failing
    otherwise with ERR_EMPLOYEE_NOT_ELIGIBLE".

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_employee_eligible
    """
    # Employee still WAITING: waiting period runs to 2026-06-01 but clock only at 2026-01-01.
    emp = setup_eligible_employee(wp_end="2026-06-01", clock_after="2026-01-01T00:00:00Z")
    # setup_eligible_employee with clock < end leaves status WAITING.
    assert emp["eligibility_status"] == "WAITING", emp
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev = employee_version(emp["id"])
    resp = api.activate_enrollment(enr["id"], {"expected_employee_version": ev}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ELIGIBLE.value)
    after = get_success_data(api.get_enrollment(enr["id"], _ADMIN))
    assert after["status"] == "DRAFT", after


def test_activate_when_waiting_employee_unchanged_state():
    """PRD §3.4: "the owning employee's eligibility_status must be ELIGIBLE, failing
    otherwise with ERR_EMPLOYEE_NOT_ELIGIBLE".

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_employee_eligible
    """
    emp = setup_eligible_employee(wp_end="2026-06-01", clock_after="2026-01-01T00:00:00Z")
    off = create_offering(benefit_type="DENTAL", name="Dental Basic")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=12000, employer_contribution_pct=0.50)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev = employee_version(emp["id"])
    resp = api.activate_enrollment(enr["id"], {"expected_employee_version": ev}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ELIGIBLE.value)

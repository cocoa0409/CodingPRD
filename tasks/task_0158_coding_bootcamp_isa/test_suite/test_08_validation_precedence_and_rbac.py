"""Validation precedence (auth vs state, state vs business-safety), not-found
existence checks, FK-filtered listing, and RBAC role isolation.

Translates difficulty `priority_pair_validation_conflict` and corner `errors`,
`endpoints`, and `rbac` instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    UNRECOGNIZED_ROLE_HEADERS,
    NONEXISTENT_UUID,
    create_cohort_payload,
    create_enrollment_payload,
    setup_active_enrollment,
    setup_isa_with_settled_payment,
    setup_isa_with_pending_payment,
    set_clock,
)

ADMIN = TEST_USERS["admissions_officer_headers"]
SERVICING = TEST_USERS["servicing_officer_headers"]
STUDENT = TEST_USERS["student_headers"]


def test_forbidden_beats_invalid_state_on_payment_settle():
    """PRD §2.8: "Authorization comes next: a recognized role lacking permission for the operation yields `ERR_FORBIDDEN`."
    PRD §2.8: "Then state: a transition attempted from a state in which it is not defined yields `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_payment_settle
    """
    # A SETTLED payment (so a re-settle would be an invalid-state) called by a
    # Student (not authorized to settle): auth wins -> 403 ERR_FORBIDDEN.
    isa, report, payment = setup_isa_with_settled_payment(gross_income_cents=600_000, email="fbeats@example.com")
    resp = api_client.settle_payment(payment["id"], STUDENT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_forbidden_returned_for_student_on_pending_payment_settle():
    """PRD §2.8: "Authorization comes next: a recognized role lacking permission for the operation yields `ERR_FORBIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_invalid_state_on_payment_settle
    """
    # A PENDING payment (a perfectly valid settle target) called by a Student:
    # auth still fires before any state evaluation -> 403 ERR_FORBIDDEN.
    isa, report, pay_id = setup_isa_with_pending_payment(gross_income_cents=600_000, email="fbeats2@example.com")
    resp = api_client.settle_payment(pay_id, STUDENT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_invalid_state_beats_dismissal_safety():
    """PRD §2.8: "Then state: a transition attempted from a state in which it is not defined yields `ERR_INVALID_STATE`."
    PRD §2.8: "Only after all of these do the domain-specific business rules described in Section 3 run; among those, each rule's own narrative states the conditions under which it fires, and where two business rules guard one operation their relative order is stated alongside them."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_dismissal_safety
    """
    # An enrollment that was fully present (attendance_pct=100, dismissal unjustified)
    # then WITHDRAWN (terminal). Dismiss attempt: state check fires before safety.
    cohort, applicant, enrollment = setup_active_enrollment(
        "UPFRONT", email="sbeats@example.com", present=True, progress_pct=60
    )
    get_success_data(api_client.withdraw_enrollment(enrollment["id"], ADMIN, {"refund_reason": "WITHDRAWAL"}))
    resp = api_client.dismiss_enrollment(enrollment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_returned_dismissing_graduated_enrollment():
    """PRD §2.8: "Then state: a transition attempted from a state in which it is not defined yields `ERR_INVALID_STATE`."
    PRD §2.8: "Only after all of these do the domain-specific business rules described in Section 3 run; among those, each rule's own narrative states the conditions under which it fires, and where two business rules guard one operation their relative order is stated alongside them."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_dismissal_safety
    """
    # A GRADUATED (terminal) enrollment with attendance_pct=100 (dismissal would be
    # unjustified). Dismiss: the state guard fires before the safety business rule.
    from test_helpers import setup_graduated_upfront
    cohort, applicant, enrollment = setup_graduated_upfront(email="grad-dismiss@example.com")
    resp = api_client.dismiss_enrollment(enrollment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_enrollment_unknown_applicant_returns_not_found():
    """PRD §2.6: "The same left-to-right existence discipline applies to identifiers supplied in a request body: a create whose body references a non-existent parent is a `ERR_NOT_FOUND`, evaluated before deeper business rules run."

    Design: Corner/errors/enrollment_unknown_applicant_returns_not_found
    """
    resp = api_client.create_enrollment(
        create_enrollment_payload(NONEXISTENT_UUID, "UPFRONT"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_fk_filtered_list_payments_by_income_report():
    """PRD §3.8: "The payment that results records the `isa_contract_id` of the contract being paid down, the `income_report_id` of the report that generated it, and an `amount_cents` equal to the report's `obligation_cents` at creation time."

    Design: Corner/endpoints/fk_filtered_list_payments_by_income_report
    """
    isa, report, pay_id = setup_isa_with_pending_payment(gross_income_cents=600_000, email="fklist@example.com")
    data = get_success_data(api_client.list_payments(SERVICING, params={"income_report_id": report["id"]}))
    rows = data if isinstance(data, list) else data["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == pay_id


def test_student_cannot_create_cohort_forbidden():
    """PRD §2.1: "When the role is recognized but is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/student_cannot_create_cohort_forbidden
    """
    set_clock("2026-01-01T00:00:00Z", ADMIN)
    resp = api_client.create_cohort(create_cohort_payload(), STUDENT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_admissions_officer_cannot_settle_payment_forbidden():
    """PRD §2.1: "When the role is recognized but is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/admissions_officer_cannot_settle_payment_forbidden
    """
    isa, report, pay_id = setup_isa_with_pending_payment(gross_income_cents=600_000, email="aosettle@example.com")
    resp = api_client.settle_payment(pay_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_returns_unauthenticated():
    """PRD §2.1: "If the `X-User-Role` header is absent or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api_client.list_cohorts(UNRECOGNIZED_ROLE_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

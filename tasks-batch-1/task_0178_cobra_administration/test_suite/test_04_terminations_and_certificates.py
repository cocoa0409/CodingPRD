"""Enrollment terminations (early, run-to-term, recurring nonpayment) and the
HIPAA certificates they mint.

Covers difficulty instances enrollment_branch_terminate_early_vs_run_to_term,
nonpayment_tick_cascade_enrollment_to_invoices_to_certificate,
hipaa_certificate_conserves_creditable_month_count,
payment_requires_enrollment_not_terminated, and corner state-machine instances
(run-to-term cert, terminal lockdown).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    assert_enrollment, assert_certificate, assert_no_version_field, date_equals,
    create_payment_payload, terminate_early_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

_ADMIN = TEST_USERS["plan_administrator_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def test_terminate_early_sets_reason_and_end_date_to_clock(api):
    """PRD §3.9: "A valid early termination moves the enrollment from ACTIVE to
    TERMINATED, records the supplied reason into termination_reason, and sets
    actual_end_date to the current clock (the end of the current paid period)."
    PRD §3.9: "bubbles the beneficiary's status to COVERAGE_ENDED".

    Design: Difficulty/non_linear_state_machine/enrollment_branch_terminate_early_vs_run_to_term
    """
    ctx = fx.setup_active_enrollment()  # April paid
    enr_id = ctx["enrollment"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    fx.set_clock("2026-06-15T00:00:00.000Z")
    resp = api.terminate_early(enr_id, terminate_early_payload("OTHER_GROUP_COVERAGE"), _ADMIN)
    enr = validate_success(resp, 200)
    assert_enrollment(enr)
    assert enr["status"] == "TERMINATED", f"enrollment {enr['status']}"
    assert enr["termination_reason"] == "OTHER_GROUP_COVERAGE", f"reason {enr['termination_reason']}"
    assert date_equals(enr["actual_end_date"], "2026-06-15"), (
        f"actual_end_date {enr['actual_end_date']}"
    )
    ben = validate_success(api.get_beneficiary(ben_id, _ADMIN))
    assert ben["status"] == "COVERAGE_ENDED", f"beneficiary {ben['status']}"


def test_run_to_term_tick_terminates_at_scheduled_end(api):
    """PRD §3.10: "an ACTIVE enrollment whose scheduled_end_date the clock has
    passed runs to term. It moves to TERMINATED with termination_reason
    RUN_TO_TERM and actual_end_date equal to the scheduled_end_date".

    Design: Difficulty/non_linear_state_machine/enrollment_branch_terminate_early_vs_run_to_term
    """
    ctx = fx.setup_active_enrollment()  # 18-month TERMINATION, scheduled_end 2027-09-30
    plan_id = ctx["plan"]["id"]
    enr_id = ctx["enrollment"]["id"]
    fx.set_clock("2027-10-05T00:00:00.000Z")  # past scheduled_end
    api.tick(plan_id, _ADMIN)
    enr = validate_success(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "TERMINATED", f"enrollment {enr['status']}"
    assert enr["termination_reason"] == "RUN_TO_TERM", f"reason {enr['termination_reason']}"
    assert date_equals(enr["actual_end_date"], "2027-09-30"), (
        f"actual_end_date {enr['actual_end_date']}"
    )


def test_recurring_nonpayment_tick_terminates_and_voids_trailing_invoice(api):
    """PRD §3.10: "Second, an ACTIVE enrollment whose earliest unsatisfied month
    has passed its recurring grace — that is, the first-of-month due date plus
    the plan's recurring_premium_grace_days, with the month still not fully
    satisfied — is terminated for nonpayment, but with coverage that did vest."
    PRD §3.10: "The enrollment moves to TERMINATED with termination_reason
    NONPAYMENT, and actual_end_date is set to the account's paid_through_date, so
    coverage retroactively ends at the last fully paid month."
    PRD §3.10: "The sweep voids every OPEN invoice whose coverage_month is after
    paid_through_date, bubbles the beneficiary's status to COVERAGE_ENDED, and
    creates a HIPAA certificate spanning coverage_start_date through
    actual_end_date."

    Design: Difficulty/transitive_cascade/nonpayment_tick_cascade_enrollment_to_invoices_to_certificate
    """
    ctx = fx.setup_active_enrollment()  # April paid -> paid_through 2026-04-30
    plan_id = ctx["plan"]["id"]
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    may_inv = fx.create_invoice(acct_id, "2026-05")  # OPEN, unpaid
    fx.set_clock("2026-06-05T00:00:00.000Z")  # past May recurring grace (2026-05-31)
    api.tick(plan_id, _ADMIN)
    enr = validate_success(api.get_enrollment(enr_id, _ADMIN))
    may = validate_success(api.get_invoice(may_inv["id"], _ADMIN))
    assert enr["status"] == "TERMINATED", f"enrollment {enr['status']}"
    assert enr["termination_reason"] == "NONPAYMENT", f"reason {enr['termination_reason']}"
    assert date_equals(enr["actual_end_date"], "2026-04-30"), (
        f"actual_end_date {enr['actual_end_date']}"
    )
    assert may["status"] == "VOID", f"May invoice {may['status']}"


def test_recurring_nonpayment_tick_issues_certificate_one_month(api):
    """PRD §3.10: "creates a HIPAA certificate spanning coverage_start_date
    through actual_end_date."
    PRD §3.10: "computes creditable_months as the count of whole COBRA coverage
    months between the endpoints inclusive: the through-year minus the from-year,
    multiplied by twelve, plus the through-month minus the from-month, plus one."

    Design: Difficulty/transitive_cascade/nonpayment_tick_cascade_enrollment_to_invoices_to_certificate
    """
    ctx = fx.setup_active_enrollment()  # April paid; actual_end will be 2026-04-30
    plan_id = ctx["plan"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-05")
    fx.set_clock("2026-06-05T00:00:00.000Z")
    api.tick(plan_id, _ADMIN)
    cert = fx.first_certificate_for_beneficiary(ben_id)
    assert_certificate(cert)
    # coverage_start 2026-04, actual_end 2026-04 -> 1 month.
    assert cert["creditable_months"] == 1, f"creditable_months {cert['creditable_months']}"


def test_certificate_creditable_months_spans_paid_interval(api):
    """PRD §3.10: "sets coverage_from to the enrollment's coverage_start_date and
    coverage_through to its actual_end_date, copies the producing
    termination_reason into issued_reason".
    PRD §3.10: "computes creditable_months as the count of whole COBRA coverage
    months between the endpoints inclusive: the through-year minus the from-year,
    multiplied by twelve, plus the through-month minus the from-month, plus one."

    Design: Difficulty/compensating_invariant/hipaa_certificate_conserves_creditable_month_count
    """
    ctx = fx.setup_active_enrollment()  # April paid
    enr_id = ctx["enrollment"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    fx.set_clock("2026-06-15T00:00:00.000Z")
    fx.terminate_early(enr_id, "MEDICARE_ENTITLEMENT")  # actual_end 2026-06-15
    cert = fx.first_certificate_for_beneficiary(ben_id)
    assert_certificate(cert)
    # coverage_start 2026-04, actual_end 2026-06 -> (0*12)+(6-4)+1 = 3 months.
    assert cert["creditable_months"] == 3, f"creditable_months {cert['creditable_months']}"
    assert cert["issued_reason"] == "MEDICARE_ENTITLEMENT", f"issued_reason {cert['issued_reason']}"
    assert date_equals(cert["coverage_through"], "2026-06-15"), (
        f"coverage_through {cert['coverage_through']}"
    )


def test_certificate_creditable_months_no_double_count(api):
    """PRD §3.10: "computes creditable_months as the count of whole COBRA
    coverage months between the endpoints inclusive: the through-year minus the
    from-year, multiplied by twelve, plus the through-month minus the from-month,
    plus one."

    Design: Difficulty/compensating_invariant/hipaa_certificate_conserves_creditable_month_count
    """
    ctx = fx.setup_active_enrollment()  # April paid
    enr_id = ctx["enrollment"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    fx.set_clock("2026-06-15T00:00:00.000Z")
    fx.terminate_early(enr_id, "OTHER_GROUP_COVERAGE")
    cert = fx.first_certificate_for_beneficiary(ben_id)
    # April, May, June = exactly 3 with no drift.
    assert cert["creditable_months"] == 3, f"creditable_months {cert['creditable_months']}"


def test_payment_on_terminated_enrollment_rejected(api):
    """PRD §3.6: "Posting is permitted only while the enrollment is in
    PENDING_INITIAL_PREMIUM or ACTIVE; against any other enrollment state the
    payment is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/payment_requires_enrollment_not_terminated
    """
    ctx = fx.setup_active_enrollment()  # April paid
    enr_id = ctx["enrollment"]["id"]
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-05")
    fx.set_clock("2026-06-15T00:00:00.000Z")
    fx.terminate_early(enr_id, "OTHER_GROUP_COVERAGE")  # enrollment TERMINATED
    resp = api.create_payment(acct_id, create_payment_payload(61200, "2026-05"), _BILLING)
    validate_error(resp, "ERR_INVALID_STATE")


def test_payment_on_active_enrollment_succeeds(api):
    """PRD §3.6: "Posting is permitted only while the enrollment is in
    PENDING_INITIAL_PREMIUM or ACTIVE".

    Design: Difficulty/cross_entity_state_dependency/payment_requires_enrollment_not_terminated
    """
    ctx = fx.setup_active_enrollment()  # ACTIVE after April paid
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-05")
    resp = api.create_payment(acct_id, create_payment_payload(61200, "2026-05"), _BILLING)
    pay = validate_success(resp, 201)
    assert pay["status"] == "POSTED"


def test_run_to_term_tick_certificate_18_months(api):
    """PRD §3.10: "an ACTIVE enrollment whose scheduled_end_date the clock has
    passed runs to term. It moves to TERMINATED with termination_reason
    RUN_TO_TERM and actual_end_date equal to the scheduled_end_date, the
    beneficiary's status becomes COVERAGE_ENDED, and a HIPAA certificate is
    created spanning coverage_start_date through scheduled_end_date."

    Design: Corner/state_machines/run_to_term_tick_issues_certificate_18_months
    """
    ctx = fx.setup_active_enrollment()  # 18-month, scheduled_end 2027-09-30
    plan_id = ctx["plan"]["id"]
    enr_id = ctx["enrollment"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    fx.set_clock("2027-10-05T00:00:00.000Z")
    api.tick(plan_id, _ADMIN)
    enr = validate_success(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "TERMINATED"
    assert enr["termination_reason"] == "RUN_TO_TERM", f"reason {enr['termination_reason']}"
    cert = fx.first_certificate_for_beneficiary(ben_id)
    # coverage_start 2026-04-01, actual_end 2027-09-30 -> (1*12)+(9-4)+1 = 18.
    assert cert["creditable_months"] == 18, f"creditable_months {cert['creditable_months']}"


def test_second_terminate_early_on_terminated_enrollment_rejected(api):
    """PRD §3.9: "Early termination is permitted only while the enrollment is
    ACTIVE; from any other state the request is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/terminate_early_on_terminated_enrollment_returns_invalid_state
    """
    ctx = fx.setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    fx.set_clock("2026-06-15T00:00:00.000Z")
    fx.terminate_early(enr_id, "OTHER_GROUP_COVERAGE")  # now TERMINATED
    resp = api.terminate_early(enr_id, terminate_early_payload("MEDICARE_ENTITLEMENT"), _ADMIN)
    validate_error(resp, "ERR_INVALID_STATE")


def test_certificate_is_immutable_no_version_field(api):
    """PRD §2.4: "The HIPAA certificate is the one exception. It is an immutable
    record minted at the moment coverage ends, so it carries only id and
    created_at; it has no updated_at and no version field, because it is never
    modified after issuance."

    Design: Corner/entities/hipaa_certificate_is_immutable_no_version_field
    """
    ctx = fx.setup_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    fx.set_clock("2026-06-15T00:00:00.000Z")
    fx.terminate_early(enr_id, "OTHER_GROUP_COVERAGE")
    cert = fx.first_certificate_for_beneficiary(ben_id)
    assert cert["creditable_months"] == 3, f"creditable_months {cert['creditable_months']}"
    assert_no_version_field(cert)

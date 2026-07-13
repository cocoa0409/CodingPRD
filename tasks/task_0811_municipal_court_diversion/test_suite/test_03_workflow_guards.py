"""State-transition guards, segregation of duties, and validation-precedence pairs.

Translates queue-B state_machine and validation instances plus queue-A
priority_pair_validation_conflict.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_probation_officer_headers,
    create_diversion_payload, create_service_site_payload,
    create_service_assignment_payload, create_payment_payload, plea_payload,
    setup_arraigned_case, setup_granted_diversion, setup_accepted_diversion,
    setup_service_ready, refetch_ledger,
)

JUDGE = "judge_headers"
CASHIER = "cashier_headers"


# ---------------------------------------------------------------------------
# Queue B — state machine guards.
# ---------------------------------------------------------------------------

def test_accept_twice_second_rejected(api):
    """PRD §3.5: "acceptance requires the owning case to be in DIVERSION_GRANTED
    and moves the agreement from OFFERED to IN_PROGRESS, with no other effect
    beyond the status change and the refreshed updated_at."
    PRD §2.9: "A disallowed transition yields ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/accept_twice_second_rejected
    """
    ctx = setup_accepted_diversion(api, diversion_overrides={"mandated_service_hours": 0})
    resp = api.accept_diversion(ctx["diversion"]["id"], ctx["def_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_plea_second_time_rejected(api):
    """PRD §3.4: "a second attempt on a hearing whose plea is already set, or a
    plea value outside the three allowed strings, is rejected with
    ERR_INVALID_PLEA."

    Design: Corner/state_machines/plea_second_time_rejected
    """
    ctx = setup_arraigned_case(api, plea="GUILTY")
    resp = api.enter_plea(ctx["arraignment"]["id"], plea_payload("NOT_GUILTY"), ctx["def_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_PLEA, 422)


def test_warrant_before_deadline_rejected(api):
    """PRD §3.8: "A warrant requested while now is still at or before that deadline
    is rejected with ERR_DEADLINE_NOT_PASSED."

    Design: Corner/state_machines/warrant_before_deadline_rejected
    """
    ctx = setup_accepted_diversion(api, diversion_overrides={
        "mandated_service_hours": 0, "program_deadline": "2026-06-01T00:00:00Z"})
    # Clock is at its default 2026-03-01, before the deadline.
    resp = api.issue_warrant(ctx["case"]["id"], TEST_USERS[JUDGE])
    validate_error(resp, ApiErrorId.ERR_DEADLINE_NOT_PASSED, 422)


def test_dismiss_before_complied_rejected(api):
    """PRD §3.9: "Dismissal is permitted only while the case is in COMPLIED and
    only when the diversion agreement is COMPLETED."
    PRD §2.9: "A disallowed transition yields ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/dismiss_before_complied_rejected
    """
    ctx = setup_accepted_diversion(api, diversion_overrides={"mandated_service_hours": 0})
    resp = api.dismiss_case(ctx["case"]["id"], TEST_USERS[JUDGE])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_payment_double_reverse_rejected(api):
    """PRD §3.7: "A payment that has already been reversed cannot be reversed
    again; a second attempt is rejected with ERR_PAYMENT_ALREADY_REVERSED."

    Design: Corner/state_machines/payment_double_reverse_rejected
    """
    ctx = setup_granted_diversion(api, diversion_overrides={"mandated_service_hours": 0, "program_fee": 100})
    account = ctx["ledger_account"]
    payment = validate_success(
        api.create_payment(account["id"], create_payment_payload(200.00), TEST_USERS[CASHIER]), 201)
    validate_success(api.reverse_payment(payment["id"], TEST_USERS[CASHIER]), 200)
    resp = api.reverse_payment(payment["id"], TEST_USERS[CASHIER])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_REVERSED, 409)


# ---------------------------------------------------------------------------
# Queue B — safety-tier verification guards (isolated single-failure scenarios).
# ---------------------------------------------------------------------------

def test_segregation_same_officer_verify_rejected(api):
    """PRD §3.6: "The verifier's X-User-ID must differ from the assignment's
    assigned_by_officer_id — the officer who created an assignment may not be the
    one who verifies it — and a match is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/validations/segregation_same_officer_verify_rejected
    """
    ctx = setup_service_ready(api, pay_ledger=True, creator_officer_id="po_1",
                              required_hours=10, hours_logged=10)
    # Same officer (po_1) who created the assignment attempts to verify it.
    same_officer = make_probation_officer_headers("po_1")
    resp = api.verify_completion(ctx["assignment"]["id"], same_officer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


def test_verify_insufficient_hours_rejected(api):
    """PRD §3.6: "The assignment's completed_hours must be at least its
    required_hours; a shortfall is rejected with ERR_ASSIGNMENT_NOT_VERIFIABLE."

    Design: Corner/validations/assignment_not_verifiable_insufficient_hours_rejected
    """
    ctx = setup_service_ready(api, pay_ledger=True, creator_officer_id="po_1",
                              required_hours=10, hours_logged=5)
    verifier = make_probation_officer_headers("po_2")
    resp = api.verify_completion(ctx["assignment"]["id"], verifier)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_VERIFIABLE, 409)


# ---------------------------------------------------------------------------
# Rule 5 — validation precedence: closed-account (state) beats overpayment (fiscal).
# ---------------------------------------------------------------------------

def _closed_account_id(api):
    ctx = setup_service_ready(api, pay_ledger=True, creator_officer_id="po_1",
                              required_hours=10, hours_logged=10)
    validate_success(
        api.verify_completion(ctx["assignment"]["id"], make_probation_officer_headers("po_2")), 200)
    validate_success(api.dismiss_case(ctx["case"]["id"], TEST_USERS[JUDGE]), 200)
    return ctx["ledger_account"]["id"]


def test_closed_account_beats_overpayment_small_amount(api):
    """PRD §2.9: "At this same tier, a payment or plan against a closed account
    yields ERR_ACCOUNT_CLOSED (409)."
    PRD §3.9: "A closed account is frozen: any later payment or plan against it is
    rejected with ERR_ACCOUNT_CLOSED."

    Design: Difficulty/priority_pair_validation_conflict/closed_account_beats_overpayment_on_payment
    """
    account_id = _closed_account_id(api)
    resp = api.create_payment(account_id, create_payment_payload(10.00), TEST_USERS[CASHIER])
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED, 409)


def test_closed_account_beats_overpayment_large_amount(api):
    """PRD §2.9: "the tiers exist so that, for example, an authorization failure is
    never masked by a state failure that would also apply."
    PRD §3.9: "any later payment or plan against it is rejected with
    ERR_ACCOUNT_CLOSED."

    Design: Difficulty/priority_pair_validation_conflict/closed_account_beats_overpayment_on_payment
    """
    account_id = _closed_account_id(api)
    # An amount that would also be an overpayment; the state tier still wins.
    resp = api.create_payment(account_id, create_payment_payload(600.00), TEST_USERS[CASHIER])
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED, 409)


# ---------------------------------------------------------------------------
# Rule 5 — validation precedence: ineligible type (referential) beats site
# capacity (constraint) on assignment creation.
# ---------------------------------------------------------------------------

def test_ineligible_type_beats_site_capacity(api):
    """PRD §3.6: "The assignment_type must match the hosting site's site_type; a
    mismatch is rejected with ERR_CHARGE_NOT_ELIGIBLE."
    PRD §2.9: "Business referential — first-offender eligibility
    (ERR_NOT_FIRST_OFFENDER, 422) and charge/assignment eligibility
    (ERR_CHARGE_NOT_ELIGIBLE, 422)."
    PRD §2.9: "Business constraint — courtroom double-booking
    (ERR_COURTROOM_DOUBLE_BOOKED, 409), service-site capacity
    (ERR_SERVICE_SITE_AT_CAPACITY, 409)"

    Design: Difficulty/priority_pair_validation_conflict/ineligible_type_beats_site_capacity_on_assignment
    """
    ctx = setup_accepted_diversion(api, diversion_overrides={
        "mandated_service_hours": 10, "required_class_sessions": 1})
    admin = TEST_USERS["court_admin_headers"]
    officer = make_probation_officer_headers("po_1")
    site = validate_success(api.create_service_site(
        create_service_site_payload(site_type="COMMUNITY_SERVICE", concurrent_capacity=1), admin), 201)
    # Fill the site's single slot with an overlapping COMMUNITY_SERVICE assignment.
    validate_success(api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(
            site["id"], assignment_type="COMMUNITY_SERVICE", required_hours=5,
            session_start="2026-03-10T10:00:00Z", session_end="2026-03-10T12:00:00Z"),
        officer), 201)
    # New assignment violates BOTH type-match (pri 6) and capacity (pri 9); referential wins.
    resp = api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(
            site["id"], assignment_type="EDUCATION_CLASS", required_hours=3,
            session_start="2026-03-10T10:30:00Z", session_end="2026-03-10T11:00:00Z"),
        officer)
    validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_ELIGIBLE, 422)


def test_assignment_type_mismatch_rejected_isolated(api):
    """PRD §3.6: "The assignment_type must match the hosting site's site_type; a
    mismatch is rejected with ERR_CHARGE_NOT_ELIGIBLE."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_type_beats_site_capacity_on_assignment
    """
    ctx = setup_accepted_diversion(api, diversion_overrides={
        "mandated_service_hours": 10, "required_class_sessions": 1})
    admin = TEST_USERS["court_admin_headers"]
    officer = make_probation_officer_headers("po_1")
    # Empty COMMUNITY_SERVICE site with ample capacity: only the type mismatch can fail.
    site = validate_success(api.create_service_site(
        create_service_site_payload(site_type="COMMUNITY_SERVICE", concurrent_capacity=5), admin), 201)
    resp = api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(
            site["id"], assignment_type="EDUCATION_CLASS", required_hours=3,
            session_start="2026-03-11T10:00:00Z", session_end="2026-03-11T11:00:00Z"),
        officer)
    validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_ELIGIBLE, 422)

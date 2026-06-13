"""Election cascade, event/notice/enrollment lifecycle branches, and the
60-day election window boundary.

Covers difficulty instances election_cascade_event_to_notice_to_enrollment...,
qualifying_event_branch_elected_vs_lapsed, election_at_deadline_succeeds...,
send_notice_requires_beneficiary_active_employee_coverage, and corner
state-machine instances (bubble-up, pending nonpayment, void invalid state).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    assert_enrollment, assert_account, assert_notice, date_equals,
    TEST_USERS, make_beneficiary_headers,
)
from test_helpers import fixtures as fx

_ADMIN = TEST_USERS["plan_administrator_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def test_election_cascade_creates_enrollment_and_account(api):
    """PRD §3.4: "A COBRA enrollment is created: it records the notice_id it
    sprang from, copies down the beneficiary_id and event_id, stamps elected_at
    with the current clock, and computes its dates."
    PRD §3.4: "The same election simultaneously creates the premium account for
    that enrollment — one account per enrollment."

    Design: Difficulty/transitive_cascade/election_cascade_event_to_notice_to_enrollment_to_account
    """
    set = fx.set_clock
    set("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])
    notice = fx.send_notice(event["id"])
    set("2026-04-10T00:00:00.000Z")
    resp = api.elect(notice["id"], make_beneficiary_headers(ben["id"]))
    enr = validate_success(resp, 201)
    assert_enrollment(enr)
    assert enr["status"] == "PENDING_INITIAL_PREMIUM", f"enrollment status {enr['status']}"
    assert date_equals(enr["coverage_start_date"], "2026-04-01"), (
        f"coverage_start_date {enr['coverage_start_date']}"
    )
    # Account created with computed premium and initial due date.
    acct = fx.get_account_for_enrollment(enr["id"])
    assert_account(acct)
    assert acct["monthly_premium_cents"] == 61200, f"monthly_premium {acct['monthly_premium_cents']}"
    # elected_at 2026-04-10 + 45 grace days = 2026-05-25.
    assert date_equals(acct["initial_premium_due_date"], "2026-05-25"), (
        f"initial_premium_due_date {acct['initial_premium_due_date']}"
    )


def test_election_marks_notice_and_event_elected(api):
    """PRD §3.4: "The notice moves to ELECTED and the originating event also
    moves to ELECTED."

    Design: Difficulty/transitive_cascade/election_cascade_event_to_notice_to_enrollment_to_account
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])
    notice = fx.send_notice(event["id"])
    fx.set_clock("2026-04-10T00:00:00.000Z")
    api.elect(notice["id"], make_beneficiary_headers(ben["id"]))
    notice_now = validate_success(api.get_notice(notice["id"], _ADMIN))
    event_now = validate_success(api.get_event(event["id"], _ADMIN))
    assert notice_now["status"] == "ELECTED", f"notice {notice_now['status']}"
    assert event_now["status"] == "ELECTED", f"event {event_now['status']}"


def test_outstanding_notice_lapses_via_tick_past_deadline(api):
    """PRD §3.4: "When the administrator runs the sweep and the current clock is
    strictly past a notice's election_deadline while the notice is still
    OUTSTANDING, the sweep moves the notice to EXPIRED, moves the originating
    event to LAPSED, and bubbles the beneficiary's status to COVERAGE_ENDED."

    Design: Difficulty/non_linear_state_machine/qualifying_event_branch_elected_vs_lapsed
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])  # deadline 2026-05-31
    notice = fx.send_notice(event["id"])
    fx.set_clock("2026-06-05T00:00:00.000Z")  # past deadline
    api.tick(plan["id"], _ADMIN)
    event_now = validate_success(api.get_event(event["id"], _ADMIN))
    notice_now = validate_success(api.get_notice(notice["id"], _ADMIN))
    ben_now = validate_success(api.get_beneficiary(ben["id"], _ADMIN))
    assert event_now["status"] == "LAPSED", f"event {event_now['status']}"
    assert notice_now["status"] == "EXPIRED", f"notice {notice_now['status']}"
    assert ben_now["status"] == "COVERAGE_ENDED", f"beneficiary {ben_now['status']}"


def test_election_path_creates_enrollment_branch(api):
    """PRD §3.4: "A valid election sets off the deepest cascade in the system.
    The notice moves to ELECTED and the originating event also moves to ELECTED.
    A COBRA enrollment is created".

    Design: Difficulty/non_linear_state_machine/qualifying_event_branch_elected_vs_lapsed
    """
    # The ELECTED fork of the same NOTICE_SENT state: electing within the window
    # creates an enrollment, the opposite outcome to the lapse branch above.
    ctx = fx.setup_elected_enrollment()
    event_now = validate_success(api.get_event(ctx["event"]["id"], _ADMIN))
    assert event_now["status"] == "ELECTED", f"event {event_now['status']}"
    assert ctx["enrollment"]["status"] == "PENDING_INITIAL_PREMIUM"


def test_election_exactly_at_deadline_succeeds(api):
    """PRD §3.4: "It is also bounded in time: the current clock must be on or
    before the notice's election_deadline. An election attempted after the
    deadline (clock strictly later than election_deadline) is rejected with
    ERR_ELECTION_WINDOW_CLOSED."

    Design: Difficulty/boundary_precision_check/election_at_deadline_succeeds_day_after_closed
    """
    fx.set_clock("2026-03-25T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])
    notice = fx.send_notice(event["id"])  # anchor max(2026-04-01, 2026-03-25)=2026-04-01, deadline 2026-05-31
    fx.set_clock("2026-05-31T00:00:00.000Z")  # exactly at deadline
    resp = api.elect(notice["id"], make_beneficiary_headers(ben["id"]))
    enr = validate_success(resp, 201)
    assert enr["status"] == "PENDING_INITIAL_PREMIUM"
    notice_now = validate_success(api.get_notice(notice["id"], _ADMIN))
    assert_notice(notice_now)
    assert notice_now["status"] == "ELECTED", f"notice {notice_now['status']}"
    assert date_equals(notice_now["election_deadline"], "2026-05-31"), (
        f"election_deadline {notice_now['election_deadline']}"
    )


def test_election_day_after_deadline_rejected(api):
    """PRD §3.4: "An election attempted after the deadline (clock strictly later
    than election_deadline) is rejected with ERR_ELECTION_WINDOW_CLOSED."

    Design: Difficulty/boundary_precision_check/election_at_deadline_succeeds_day_after_closed
    """
    fx.set_clock("2026-03-25T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])  # deadline 2026-05-31
    notice = fx.send_notice(event["id"])
    fx.set_clock("2026-06-01T00:00:00.000Z")  # one day past deadline
    resp = api.elect(notice["id"], make_beneficiary_headers(ben["id"]))
    validate_error(resp, "ERR_ELECTION_WINDOW_CLOSED")


def test_send_notice_requires_active_employee_coverage(api):
    """PRD §3.3: "A beneficiary who is not in ACTIVE_EMPLOYEE_COVERAGE causes the
    request to be rejected with ERR_BENEFICIARY_NOT_ELIGIBLE."

    Design: Difficulty/cross_entity_state_dependency/send_notice_requires_beneficiary_active_employee_coverage
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event1 = fx.create_event(plan["id"], ben["id"], event_type="TERMINATION")
    fx.send_notice(event1["id"])  # beneficiary now COBRA_ELIGIBLE
    event2 = fx.create_event(plan["id"], ben["id"], event_type="REDUCTION_OF_HOURS")
    resp = api.send_notice(event2["id"], _ADMIN)
    validate_error(resp, "ERR_BENEFICIARY_NOT_ELIGIBLE")
    event2_now = validate_success(api.get_event(event2["id"], _ADMIN))
    assert event2_now["status"] == "RECORDED", f"event2 {event2_now['status']}"


def test_send_notice_succeeds_while_beneficiary_eligible(api):
    """PRD §3.3: "It also requires that the beneficiary still be eligible: the
    beneficiary's status must be ACTIVE_EMPLOYEE_COVERAGE, so that an
    already-enrolled or already-ended beneficiary cannot receive a fresh notice
    on the same active coverage."

    Design: Difficulty/cross_entity_state_dependency/send_notice_requires_beneficiary_active_employee_coverage
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])  # ACTIVE_EMPLOYEE_COVERAGE
    event = fx.create_event(plan["id"], ben["id"])
    resp = api.send_notice(event["id"], _ADMIN)
    notice = validate_success(resp, 201)
    assert notice["status"] == "OUTSTANDING"
    ben_now = validate_success(api.get_beneficiary(ben["id"], _ADMIN))
    assert ben_now["status"] == "COBRA_ELIGIBLE", f"beneficiary {ben_now['status']}"


def test_first_payment_bubbles_pending_enrollment_to_active(api):
    """PRD §3.6: "the enrollment bubbles from PENDING_INITIAL_PREMIUM to ACTIVE
    and the account's paid_through_date is recomputed to the last day of month 1.
    This is the moment COBRA coverage vests."

    Design: Corner/state_machines/payment_flips_pending_enrollment_to_active_bubble_up
    """
    ctx = fx.setup_elected_enrollment()  # PENDING; elect at 2026-04-10; due 2026-05-25
    acct_id = ctx["account"]["id"]
    enr_id = ctx["enrollment"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    fx.create_invoice(acct_id, "2026-04")
    fx.set_clock("2026-04-20T00:00:00.000Z")  # before due
    fx.post_payment(acct_id, 61200, "2026-04", beneficiary_id=ben_id)
    enr = validate_success(api.get_enrollment(enr_id, _ADMIN))
    acct = validate_success(api.get_account(acct_id, _BILLING))
    assert enr["status"] == "ACTIVE", f"enrollment {enr['status']}"
    assert date_equals(acct["paid_through_date"], "2026-04-30"), (
        f"paid_through_date {acct['paid_through_date']}"
    )


def test_pending_enrollment_nonpayment_tick_terminates_without_certificate(api):
    """PRD §3.10: "an enrollment still in PENDING_INITIAL_PREMIUM whose
    initial_premium_due_date the clock has passed, with coverage month 1 not
    fully satisfied, is terminated for nonpayment before any coverage vested. The
    enrollment moves to TERMINATED with termination_reason NONPAYMENT, and its
    actual_end_date is set to the coverage_start_date minus one day".
    PRD §3.10: "Because no month was ever paid, no HIPAA certificate is issued in
    this case (the creditable-month count would be zero)."

    Design: Corner/state_machines/initial_premium_nonpayment_tick_terminates_no_certificate
    """
    ctx = fx.setup_elected_enrollment()  # PENDING, never paid; due 2026-05-25
    plan_id = ctx["plan"]["id"]
    enr_id = ctx["enrollment"]["id"]
    ben_id = ctx["beneficiary"]["id"]
    fx.set_clock("2026-05-26T00:00:00.000Z")  # past initial due
    api.tick(plan_id, _ADMIN)
    enr = validate_success(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "TERMINATED", f"enrollment {enr['status']}"
    assert enr["termination_reason"] == "NONPAYMENT", f"reason {enr['termination_reason']}"
    assert date_equals(enr["actual_end_date"], "2026-03-31"), (
        f"actual_end_date {enr['actual_end_date']}"
    )
    certs = validate_success(api.list_beneficiary_certificates(ben_id, _ADMIN))
    assert len(certs) == 0, f"expected no certificate, got {len(certs)}"


def test_void_event_after_notice_sent_rejected(api):
    """PRD §3.2: "Voiding is permitted only while the event is RECORDED;
    attempting it from any other status is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/void_event_after_notice_sent_returns_invalid_state
    """
    fx.set_clock("2026-03-20T00:00:00.000Z")
    plan = fx.create_plan()
    ben = fx.create_beneficiary(plan["id"])
    event = fx.create_event(plan["id"], ben["id"])
    fx.send_notice(event["id"])  # event now NOTICE_SENT
    resp = api.void_event(event["id"], _ADMIN)
    validate_error(resp, "ERR_INVALID_STATE")
    event_now = validate_success(api.get_event(event["id"], _ADMIN))
    assert event_now["status"] == "NOTICE_SENT", f"event {event_now['status']}"

"""State-machine transitions: loan renewal self-loop, reservation branching,
invalid transitions, precondition enforcement, ILL pipeline, fine settlement.

Queue A: non_linear_state_machine. Queue B: state_machines section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_patron_headers, TEST_USERS,
    setup_active_loan, setup_room_with_confirmed_reservation,
    setup_blocked_patron_via_lost, get_only_unpaid_fine,
    create_branch, create_patron, create_title, create_copy, create_loan,
    create_resource, create_reservation, set_clock,
)
from test_helpers import api_client as _client  # noqa

LIBRARIAN = TEST_USERS["librarian_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


# =========================================================================
# Queue A — non_linear_state_machine
# =========================================================================
def test_loan_renewal_self_loop_keeps_active(api):
    """PRD §3.3: "A successful renewal increments `renewal_count` by one, advances
    `due_date` by another `loan_period_days`, and increments the loan's `version`."
    PRD §3.3: "Renewal is a self-loop that keeps a loan `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/loan_renewal_self_loop_cyclic
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7}, isbn="9780000000006",
        clock="2026-06-01T00:00:00Z")
    ph = make_patron_headers(patron["id"])

    r1 = validate_success(api.renew_loan(loan["id"], ph), 200)
    assert r1["renewal_count"] == 1 and r1["status"] == "ACTIVE"

    r2 = validate_success(api.renew_loan(loan["id"], ph), 200)
    assert r2["renewal_count"] == 2 and r2["status"] == "ACTIVE"
    # checkout 2026-06-01 + 7 + 7 + 7 = 2026-06-22.
    assert r2["due_date"].startswith("2026-06-22"), f"due_date {r2['due_date']}"


def test_reservation_confirmed_to_checked_in_stamps_field(api):
    """PRD §3.7: "check-in stamps `checked_in_at`, moves the reservation
    `CONFIRMED → CHECKED_IN`, and increments its `version`."

    Design: Difficulty/non_linear_state_machine/reservation_confirmed_branches_to_divergent_terminals
    """
    branch, patron, resource, reservation = setup_room_with_confirmed_reservation(
        buffer_minutes=15, clock_before="2026-06-01T09:00:00Z",
        start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    set_clock("2026-06-01T10:05:00Z")
    res = validate_success(api.checkin_reservation(reservation["id"], LIBRARIAN), 200)
    assert res["status"] == "CHECKED_IN"
    assert res["checked_in_at"] is not None
    assert res["checked_in_at"].startswith("2026-06-01T10:05:00")


def test_reservation_confirmed_to_no_show_records_no_checkin(api):
    """PRD §3.7: "A confirmed reservation whose window has fully elapsed without a
    check-in is marked a no-show by a librarian — permitted only from `CONFIRMED`
    and only once the clock has reached `end_at`, otherwise `ERR_NOT_YET_DUE` —
    moving it `CONFIRMED → NO_SHOW`, which frees the window without ever recording
    a check-in."

    Design: Difficulty/non_linear_state_machine/reservation_confirmed_branches_to_divergent_terminals
    """
    branch, patron, resource, reservation = setup_room_with_confirmed_reservation(
        buffer_minutes=15, clock_before="2026-06-01T09:00:00Z",
        start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    set_clock("2026-06-01T11:05:00Z")
    res = validate_success(api.no_show_reservation(reservation["id"], LIBRARIAN), 200)
    assert res["status"] == "NO_SHOW"
    assert res["checked_in_at"] is None, "NO_SHOW fork records no check-in"


# =========================================================================
# Queue B — state_machines
# =========================================================================
def test_renew_returned_loan_invalid_state(api):
    """PRD §3.3: "A renewal is permitted only when the loan is still `ACTIVE`".
    PRD §3.8: "Each transition is rejected with `ERR_INVALID_STATE` when the
    request is not in the required source state".

    Design: Corner/state_machines/renew_returned_loan_returns_invalid_state
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7}, isbn="9782222222222",
        clock="2026-06-01T00:00:00Z")
    validate_success(api.checkin_loan(loan["id"], LIBRARIAN), 200)
    res = api.renew_loan(loan["id"], make_patron_headers(patron["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_loan(loan["id"], LIBRARIAN), 200)
    assert after["status"] == "RETURNED"


def test_confirm_already_confirmed_reservation_invalid_state(api):
    """PRD §3.7: "A requested reservation is confirmed by a librarian, permitted
    only from `REQUESTED` and only while the resource is `IN_SERVICE`".

    Design: Corner/state_machines/confirm_already_confirmed_reservation_returns_invalid_state
    """
    branch, patron, resource, reservation = setup_room_with_confirmed_reservation(
        buffer_minutes=0, clock_before="2026-06-01T09:00:00Z",
        start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    res = api.confirm_reservation(reservation["id"], LIBRARIAN)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_reservation(reservation["id"], LIBRARIAN), 200)
    assert after["status"] == "CONFIRMED"


def test_refresh_overdue_before_due_not_yet_due(api):
    """PRD §3.3: "Invoking the refresh before the clock has actually passed the
    `due_date` is rejected with `ERR_NOT_YET_DUE`."

    Design: Corner/state_machines/refresh_overdue_before_due_returns_not_yet_due
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7}, isbn="9783333333333",
        clock="2026-06-01T00:00:00Z")
    # due 2026-06-08; clock 2026-06-02 (before due).
    set_clock("2026-06-02T00:00:00Z")
    res = api.refresh_overdue(loan["id"], LIBRARIAN)
    validate_error(res, "ERR_NOT_YET_DUE")
    after = validate_success(api.get_loan(loan["id"], LIBRARIAN), 200)
    assert after["status"] == "ACTIVE"


def test_hold_checkout_while_waiting_not_ready(api):
    """PRD §3.6: "A `READY` hold is fulfilled when a librarian checks out the
    reserved copy on behalf of the hold's patron; this is permitted only while the
    hold is `READY` and the current clock is at or before its `pickup_deadline`
    (otherwise `ERR_HOLD_NOT_READY`, or `ERR_PICKUP_EXPIRED` once the deadline has
    passed)."

    Design: Corner/state_machines/hold_checkout_while_waiting_returns_hold_not_ready
    """
    branch = create_branch(loan_period_days=7)
    set_clock("2026-06-01T00:00:00Z")
    pa = create_patron(branch["id"], full_name="HNR Pat A")
    pb = create_patron(branch["id"], full_name="HNR Pat B")
    title = create_title(branch["id"], "9784444444444", title_text="HNR Book")
    copy = create_copy(title["id"], branch["id"], "BC-HN")
    create_loan(copy["id"], pa["id"])  # only copy ON_LOAN
    hold = get_success_data(_client.create_hold(
        {"title_id": title["id"], "patron_id": pb["id"]}, make_patron_headers(pb["id"])))
    res = api.checkout_hold(hold["id"], LIBRARIAN)
    validate_error(res, "ERR_HOLD_NOT_READY")


def test_ill_transition_unknown_action_invalid_action(api):
    """PRD §3.8: "An `action` value that is not one of these verbs is rejected with
    `ERR_INVALID_ACTION`."

    Design: Corner/state_machines/ill_transition_unknown_action_returns_invalid_action
    """
    branch = create_branch()
    patron = create_patron(branch["id"], full_name="ILL Pat")
    ill = get_success_data(_client.create_ill_request(
        {"patron_id": patron["id"], "branch_id": branch["id"], "isbn": "9785555555555"},
        make_patron_headers(patron["id"])))
    res = api.transition_ill(ill["id"], "teleport", LIBRARIAN)
    validate_error(res, "ERR_INVALID_ACTION")
    after = validate_success(api.get_ill_request(ill["id"], LIBRARIAN), 200)
    assert after["status"] == "REQUESTED"


def test_ill_approve_blocked_when_patron_blocked(api):
    """PRD §3.8: "The `approve` action moves a request `REQUESTED → APPROVED`, but
    only if the requesting patron's `borrowing_status` is `CLEAR`."
    PRD §2.8: "A `BLOCKED` patron may not check out, place a hold, check out an
    e-book, or reserve a room or computer, and such attempts are rejected with
    `ERR_PATRON_BLOCKED`."

    Design: Corner/state_machines/ill_approve_blocked_when_patron_blocked
    """
    branch, patron, title, copy, loan = setup_blocked_patron_via_lost(
        block_threshold_cents=1000, default_replacement_cents=2000,
        clock="2026-06-01T00:00:00Z", isbn="9786666666666")
    ill = get_success_data(_client.create_ill_request(
        {"patron_id": patron["id"], "branch_id": branch["id"], "isbn": "9786666666666"},
        LIBRARIAN))
    res = api.transition_ill(ill["id"], "approve", LIBRARIAN)
    validate_error(res, "ERR_PATRON_BLOCKED")


def test_ill_receive_creates_ill_fee_fine(api):
    """PRD §3.8: "The `receive` action moves a `SHIPPED` request to `RECEIVED` and,
    as a side effect, creates a `Fine` with `fine_type` `ILL_FEE`, `amount_cents`
    equal to the request's `lending_fee_cents`, and `loan_id` null (an ILL fee has
    no originating loan); the patron's `total_owed_cents` and then
    `borrowing_status` are recomputed."

    Design: Corner/state_machines/ill_receive_creates_ill_fee_fine
    """
    branch = create_branch(block_threshold_cents=100000)
    patron = create_patron(branch["id"], full_name="ILL Fee Pat")
    ill = get_success_data(_client.create_ill_request(
        {"patron_id": patron["id"], "branch_id": branch["id"],
         "isbn": "9787777777777", "lending_fee_cents": 500},
        make_patron_headers(patron["id"])))
    api.transition_ill(ill["id"], "approve", LIBRARIAN)
    api.transition_ill(ill["id"], "ship", LIBRARIAN)
    received = validate_success(api.transition_ill(ill["id"], "receive", LIBRARIAN), 200)
    assert received["status"] == "RECEIVED"

    fine = get_only_unpaid_fine(patron["id"])
    assert fine["fine_type"] == "ILL_FEE"
    assert fine["amount_cents"] == 500
    after = validate_success(api.get_patron(patron["id"], LIBRARIAN), 200)
    assert after["total_owed_cents"] == 500


def test_fine_pay_unblocks_patron_below_threshold(api):
    """PRD §3.10: "the patron's `total_owed_cents` is recomputed; if that
    recomputed total falls below the branch's `block_threshold_cents`, the patron's
    `borrowing_status` is set back to `CLEAR`, lifting any block."

    Design: Corner/state_machines/fine_pay_unblocks_patron_when_below_threshold
    """
    branch, patron, title, copy, loan = setup_blocked_patron_via_lost(
        block_threshold_cents=1000, default_replacement_cents=2000,
        clock="2026-06-01T00:00:00Z", isbn="9788888888888")
    blocked = validate_success(api.get_patron(patron["id"], LIBRARIAN), 200)
    assert blocked["borrowing_status"] == "BLOCKED"
    fine = get_only_unpaid_fine(patron["id"])
    validate_success(api.pay_fine(fine["id"], LIBRARIAN), 200)
    after = validate_success(api.get_patron(patron["id"], LIBRARIAN), 200)
    assert after["total_owed_cents"] == 0
    assert after["borrowing_status"] == "CLEAR"

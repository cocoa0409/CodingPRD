"""Payment ledger, parallel booking/payment dimensions, confirmation gating,
cancellation money-conservation, and start-service gating.

Design queues:
  A (Difficulty): non_linear_state_machine/event_parallel_booking_and_payment_dimensions,
                  compensating_invariant/cancel_deposit_refund_money_conservation,
                  priority_pair_validation_conflict/confirm_state_beats_fiscal,
                  boundary_precision_check/start_requires_nonempty_checked_in_set
  B (Corner): deposit-not-paid, payment-exceeds-balance, invalid-state repeats
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_draft_event, create_cleared_event, create_confirmed_event,
    create_bartender, add_assignment, add_confirmed_assignment,
    create_payment_payload, TEST_USERS, ApiErrorId, make_bartender_headers,
)

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / event_parallel_booking_and_payment_dimensions
# ---------------------------------------------------------------------------
def test_deposit_advances_payment_status_but_not_booking(api):
    """PRD §3.3: "The first deposit moves payment_status from UNPAID to
    DEPOSIT_PAID; once the balance due reaches zero the status advances to
    PAID_IN_FULL."

    Design: Difficulty/non_linear_state_machine/event_parallel_booking_and_payment_dimensions
    """
    bundle = create_draft_event(api, guest_count=80,
                                event_start="2026-06-01T18:00:00Z",
                                event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    get_success_data(api.create_payment(
        ev_id, create_payment_payload("DEPOSIT", 138720), bundle["client_headers"]))
    ev = get_success_data(api.get_event(ev_id, COORD))
    assert ev["payment_status"] == "DEPOSIT_PAID"
    assert ev["booking_status"] == "DRAFT"


def test_deposit_accumulates_amount_paid(api):
    """PRD §3.2: "Payments accumulate into `amount_paid_cents`, defined as the
    sum of all `DEPOSIT` and `BALANCE` payment amounts less the sum of all
    `REFUND` amounts."

    Design: Difficulty/non_linear_state_machine/event_parallel_booking_and_payment_dimensions
    """
    bundle = create_draft_event(api, guest_count=80,
                                event_start="2026-06-01T18:00:00Z",
                                event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    get_success_data(api.create_payment(
        ev_id, create_payment_payload("DEPOSIT", 138720), bundle["client_headers"]))
    ev = get_success_data(api.get_event(ev_id, COORD))
    assert ev["amount_paid_cents"] == 138720
    assert ev["booking_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / cancel_deposit_refund_money_conservation
# ---------------------------------------------------------------------------
def test_cancel_confirmed_settles_status_and_zero_balance(api):
    """PRD §3.8: "The event's `payment_status` is then recomputed to `SETTLED`,
    its `balance_due_cents` reconciled to 0, and `amount_paid_cents` reflects
    the refund."

    Design: Difficulty/compensating_invariant/cancel_deposit_refund_money_conservation
    """
    bundle = create_confirmed_event(api, guest_count=80,
                                    event_start="2026-06-01T18:00:00Z",
                                    event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    validate_success(api.cancel_event(ev_id, bundle["client_headers"]))
    ev = get_success_data(api.get_event(ev_id, COORD))
    assert ev["booking_status"] == "CANCELLED"
    assert ev["payment_status"] == "SETTLED"
    assert ev["balance_due_cents"] == 0


def test_cancel_confirmed_conserves_money_via_fee_and_refund(api):
    """PRD §3.8: "the system creates a CANCELLATION_FEE payment equal to the
    current amount_paid_cents multiplied by 50 percent (rounded), and a REFUND
    payment equal to amount_paid_cents less that cancellation fee. Money is
    conserved — the amounts paid in, minus the refund, equal the cancellation
    fee."

    Design: Difficulty/compensating_invariant/cancel_deposit_refund_money_conservation
    """
    bundle = create_confirmed_event(api, guest_count=80,
                                    event_start="2026-06-01T18:00:00Z",
                                    event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    validate_success(api.cancel_event(ev_id, bundle["client_headers"]))
    ev = get_success_data(api.get_event(ev_id, COORD))
    # deposit 138720 - fee 69360 = 69360 net paid.
    assert ev["amount_paid_cents"] == 69360


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / confirm_state_beats_fiscal
# ---------------------------------------------------------------------------
def test_confirm_cancelled_event_returns_invalid_state(api):
    """PRD §2.7: "a stale-version edit is rejected before any state or business
    check runs, and a body that fails well-formedness is rejected before
    concurrency is examined."
    PRD §2.7: "State legality — the target resource is in a status from which
    the requested transition is defined, else ERR_INVALID_STATE (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal
    """
    bundle = create_draft_event(api)  # DRAFT, UNPAID
    ev_id = bundle["event"]["id"]
    validate_success(api.cancel_event(ev_id, bundle["client_headers"]))
    resp = api.confirm_event(ev_id, bundle["client_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_cancelled_unpaid_event_not_reported_as_deposit_error(api):
    """PRD §2.7: "State legality — the target resource is in a status from which
    the requested transition is defined, else ERR_INVALID_STATE (HTTP 409)."
    PRD §2.7: "Business-safety, temporal, and fiscal checks — the
    domain-specific rules described in §3, evaluated after the preceding gates
    pass."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal
    """
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    validate_success(api.cancel_event(ev_id, bundle["client_headers"]))
    resp = api.confirm_event(ev_id, bundle["client_headers"])
    body = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert body["error_id"] != ApiErrorId.ERR_DEPOSIT_NOT_PAID.value


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / start_requires_nonempty_checked_in_set
# ---------------------------------------------------------------------------
def test_start_without_any_checked_in_lead_rejected(api):
    """PRD §3.7: "A Coordinator starts service, advancing CONFIRMED →
    IN_PROGRESS, but only when at least one child assignment in the LEAD role
    has reached CHECKED_IN. If no lead has checked in, the start is rejected
    with ERR_NO_CHECKED_IN_STAFF (HTTP 409) — the empty checked-in set is
    explicitly a rejection."

    Design: Difficulty/boundary_precision_check/start_requires_nonempty_checked_in_set
    """
    bundle = create_confirmed_event(api)
    resp = api.start_event(bundle["event"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_NO_CHECKED_IN_STAFF.value)


def test_start_with_confirmed_but_not_checked_in_lead_rejected(api):
    """PRD §3.7: "but only when at least one child assignment in the LEAD role
    has reached CHECKED_IN. If no lead has checked in, the start is rejected
    with ERR_NO_CHECKED_IN_STAFF (HTTP 409) — the empty checked-in set is
    explicitly a rejection."

    Design: Difficulty/boundary_precision_check/start_requires_nonempty_checked_in_set
    """
    bundle = create_confirmed_event(api)
    ev_id = bundle["event"]["id"]
    bartender = create_bartender(api)
    add_confirmed_assignment(api, ev_id, bartender["id"], role_on_event="LEAD")
    resp = api.start_event(ev_id, COORD)
    validate_error(resp, ApiErrorId.ERR_NO_CHECKED_IN_STAFF.value)


# ---------------------------------------------------------------------------
# Queue B — fiscal / state validations
# ---------------------------------------------------------------------------
def test_confirm_event_without_deposit_rejected(api):
    """PRD §3.7: "the `payment_status` must be `DEPOSIT_PAID` or `PAID_IN_FULL`,
    else `ERR_DEPOSIT_NOT_PAID` (HTTP 409)."

    Design: Corner/validations/confirm_event_deposit_not_paid
    """
    bundle = create_cleared_event(api)  # cleared but UNPAID
    resp = api.confirm_event(bundle["event"]["id"], bundle["client_headers"])
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_PAID.value)


def test_balance_payment_exceeding_balance_rejected(api):
    """PRD §3.3: "A `BALANCE` payment may not exceed the current
    `balance_due_cents`, and a second `DEPOSIT` after the status already reads
    `DEPOSIT_PAID` is refused; either violation returns
    `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/validations/balance_payment_exceeds_balance
    """
    bundle = create_draft_event(api, guest_count=80,
                                event_start="2026-06-01T18:00:00Z",
                                event_end="2026-06-01T23:00:00Z")
    ev_id = bundle["event"]["id"]
    resp = api.create_payment(
        ev_id, create_payment_payload("BALANCE", 400000), bundle["client_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)


def test_cancel_already_cancelled_event_is_invalid_state(api):
    """PRD §3.7: "CLOSED and CANCELLED are the terminal booking states."
    PRD §2.7: "Terminal states reject every transition, and re-issuing a
    transition already applied is likewise an invalid-state rejection."

    Design: Corner/state_machines/cancel_already_cancelled_event_invalid_state
    """
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    validate_success(api.cancel_event(ev_id, bundle["client_headers"]))
    resp = api.cancel_event(ev_id, bundle["client_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_check_in_before_confirm_is_invalid_state(api):
    """PRD §3.5: "The assigned Bartender — and only that bartender, matched by
    ownership — checks in on the day of service, advancing CONFIRMED →
    CHECKED_IN."
    PRD §2.7: "State legality — the target resource is in a status from which
    the requested transition is defined, else ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/checkin_before_confirm_invalid_state
    """
    bundle = create_draft_event(api)
    bartender = create_bartender(api)
    asg = add_assignment(api, bundle["event"]["id"], bartender["id"], role_on_event="BACK")
    resp = api.checkin_assignment(asg["id"], make_bartender_headers(bartender["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

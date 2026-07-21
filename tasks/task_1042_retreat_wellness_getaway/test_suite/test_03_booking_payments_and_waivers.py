"""Deposit/balance payment gates, waiver lifecycle, and clearance checks."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_booking, setup_booking_deposit_paid, setup_booking_confirmed,
)
from test_helpers.factories import create_waiver_payload

_OP = TEST_USERS["operator_headers"]


def test_pay_deposit_wrong_amount_rejected(api):
    """PRD §3.3: "The deposit payment carries an `amount_cents` that must equal the booking's `deposit_cents` exactly; a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/corner_pay_deposit_wrong_amount_rejected
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    resp = api.pay_deposit(ctx["booking"]["id"], 88888, ctx["guest_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)


def test_pay_balance_without_cleared_waiver_rejected(api):
    """PRD §3.3: "Paying the balance requires that a waiver for the booking exists and has
    reached CLEARED status (otherwise ERR_WAIVER_NOT_CLEARED, HTTP 422), and the balance
    payment's amount_cents must equal the booking's balance_due_cents exactly."

    Design: Corner/validations/corner_pay_balance_without_cleared_waiver_rejected
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    booking = ctx["booking"]
    resp = api.pay_balance(booking["id"], booking["balance_due_cents"], ctx["guest_headers"])
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_CLEARED.value)


def test_check_in_before_start_date_rejected(api):
    """PRD §3.3: "the logical clock must have reached or passed the retreat's `start_date` — an earlier attempt is rejected with `ERR_CHECKIN_TOO_EARLY` (HTTP 409)."

    Design: Corner/validations/corner_checkin_too_early_rejected
    """
    ctx = setup_booking_confirmed(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    # Clock is still at the default 2026-07-01, well before start_date 2026-09-01.
    resp = api.check_in_booking(ctx["booking"]["id"], _OP)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_TOO_EARLY.value)


def test_sign_pending_waiver_moves_to_signed(api):
    """PRD §3.4: "The guest then signs the waiver, supplying a signature_name which the
    server stamps onto the record as it moves the waiver from PENDING to SIGNED."

    Design: Corner/state_machines/corner_waiver_sign_from_pending_ok
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    waiver = validate_success(api.create_waiver(create_waiver_payload(ctx["booking"]["id"]), gh), 201)
    resp = api.sign_waiver(waiver["id"], "C3", gh)
    data = validate_success(resp, 200)
    assert data["status"] == "SIGNED"


def test_second_waiver_for_booking_rejected(api):
    """PRD §3.4: "Only one waiver may exist per booking — a second attempt is rejected with `ERR_WAIVER_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/errors/corner_duplicate_waiver_rejected
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    validate_success(api.create_waiver(create_waiver_payload(ctx["booking"]["id"]), gh), 201)
    resp = api.create_waiver(
        create_waiver_payload(ctx["booking"]["id"], health_disclosures="again"), gh)
    validate_error(resp, ApiErrorId.ERR_WAIVER_ALREADY_EXISTS.value)


def test_review_already_cleared_waiver_rejected(api):
    """PRD §3.4: "A waiver's overall `status` therefore walks `PENDING` to `SIGNED` and then to either `CLEARED` or `REJECTED`, with the latter two being terminal."

    Design: Corner/state_machines/corner_review_cleared_waiver_terminal_lockdown
    """
    ctx = setup_booking_confirmed(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    # ctx["waiver"] is already CLEARED; reviewing it again must be rejected.
    resp = api.review_waiver(ctx["waiver"]["id"], "REJECT", _OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

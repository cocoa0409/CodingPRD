"""Dispute lifecycle: cyclic reopen, withdraw conservation, resolution credits,
rejection compensation, and the dispute-exceeds-balance ceiling.

Queue A (Difficulty): reopen cycle increments reopen_count, withdraw conserves
dunnable+disputed. Queue B (Corner): invalid start-review, resolve decrement,
reject compensation, exceeds-balance.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_customer,
    create_invoice,
    create_dispute,
    setup_dispute_under_review,
    setup_dispute_reopened_once,
    assert_dunnable_plus_disputed,
    create_dispute_payload,
)


# --------------------------------------------------------------------------- #
# Queue A — cyclic reopen
# --------------------------------------------------------------------------- #
def test_reopen_moves_dispute_back_to_under_review(api, ar_manager_headers):
    """PRD §3.4: "the `AR_MANAGER` may **reopen** a dispute that is
    `RESOLVED_CREDIT` or `REJECTED`, provided the underlying invoice is not in
    `PAID` or `WRITTEN_OFF`; reopening moves the dispute back to `UNDER_REVIEW`".

    Design: Difficulty/non_linear_state_machine/dispute_reopen_cycle_increments_reopen_count
    """
    customer, invoice, dispute = setup_dispute_reopened_once(
        invoice_face=50_000, dispute_amount=20_000
    )
    reopened = validate_success(api.reopen_dispute(dispute["id"], ar_manager_headers), 200)
    assert reopened["status"] == "UNDER_REVIEW"


def test_reopen_increments_reopen_count(api, ar_manager_headers):
    """PRD §3.4: "reopening moves the dispute back to `UNDER_REVIEW`, increments
    `reopen_count`, re-applies the invoice's `disputed_amount_cents` to the
    dispute amount, and recomputes the customer's `exposure_cents`."

    Design: Difficulty/non_linear_state_machine/dispute_reopen_cycle_increments_reopen_count
    """
    customer, invoice, dispute = setup_dispute_reopened_once(
        invoice_face=50_000, dispute_amount=20_000
    )
    reopened = validate_success(api.reopen_dispute(dispute["id"], ar_manager_headers), 200)
    assert reopened["reopen_count"] == 1


# --------------------------------------------------------------------------- #
# Queue A — withdraw conserves dunnable + disputed
# --------------------------------------------------------------------------- #
def test_withdraw_clears_disputed_amount(api, ar_manager_headers, ar_clerk_headers, collections_agent_headers):
    """PRD §3.4: "withdrawal clears the invoice's `disputed_amount_cents`,
    restores the invoice's dunnable balance, and recomputes the customer's
    `exposure_cents`, conserving the identity that the dunnable balance plus the
    disputed amount is unchanged across the withdraw."

    Design: Difficulty/compensating_invariant/dispute_open_then_withdraw_conserves_dunnable_plus_disputed
    """
    customer = create_customer(name="INV2")
    invoice = create_invoice(customer["id"], face_amount_cents=60_000)
    dispute = create_dispute(invoice["id"], 10_000, "QUALITY")
    validate_success(api.withdraw_dispute(dispute["id"], collections_agent_headers), 200)
    inv_after = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert inv_after["disputed_amount_cents"] == 0


def test_withdraw_conserves_dunnable_plus_disputed(api, ar_manager_headers, collections_agent_headers):
    """PRD §3.4: "conserving the identity that the dunnable balance plus the
    disputed amount is unchanged across the withdraw."

    Opening a 10000 dispute on a 60000 invoice cuts dunnable to 50000 (disputed
    10000); withdrawing restores dunnable to 60000 and disputed to 0 — the sum
    stays 60000 throughout.

    Design: Difficulty/compensating_invariant/dispute_open_then_withdraw_conserves_dunnable_plus_disputed
    """
    customer = create_customer(name="INV2b")
    invoice = create_invoice(customer["id"], face_amount_cents=60_000)
    dispute = create_dispute(invoice["id"], 10_000, "QUALITY")
    after_open = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert_dunnable_plus_disputed(after_open, 60_000)

    validate_success(api.withdraw_dispute(dispute["id"], collections_agent_headers), 200)
    after_withdraw = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert after_withdraw["balance_cents"] == 60_000
    assert_dunnable_plus_disputed(after_withdraw, 60_000)


# --------------------------------------------------------------------------- #
# Queue B — corner cases
# --------------------------------------------------------------------------- #
def test_start_review_from_under_review_is_invalid(api, ar_manager_headers):
    """PRD §3.4: "Starting review moves a dispute from `OPEN` to `UNDER_REVIEW`
    with no balance change."
    PRD §3.10: "the generic transition guard `ERR_INVALID_STATE`".

    A dispute already UNDER_REVIEW has no defined start-review transition, so a
    second start-review is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/dispute_start_review_from_under_review_invalid
    """
    customer, invoice, dispute = setup_dispute_under_review(
        invoice_face=50_000, dispute_amount=10_000, reason_code="DAMAGE"
    )
    res = api.start_review_dispute(dispute["id"], ar_manager_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_resolve_credit_decrements_invoice_balance(api, ar_manager_headers):
    """PRD §3.4: "resolution moves the dispute to `RESOLVED_CREDIT`, records that
    figure as `resolution_credit_cents`, decrements the invoice's `balance_cents`
    by the credit, clears the invoice's `disputed_amount_cents`, and recomputes
    the customer's derived fields."

    Design: Corner/state_machines/dispute_resolve_credit_decrements_invoice_balance
    """
    customer, invoice, dispute = setup_dispute_under_review(
        invoice_face=60_000, dispute_amount=4000, reason_code="PRICING"
    )
    validate_success(
        api.resolve_dispute(dispute["id"], {"resolve_credit_cents": 4000}, ar_manager_headers), 200
    )
    inv_after = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert inv_after["balance_cents"] == 56_000
    assert inv_after["disputed_amount_cents"] == 0


def test_reject_restores_dunnable_and_exposure(api, ar_manager_headers):
    """PRD §3.4: "Rejecting a dispute under review moves it to `REJECTED`, clears
    the invoice's `disputed_amount_cents`, restores the invoice's dunnable
    balance, and recomputes the customer's `exposure_cents` and `credit_status`".

    Design: Corner/state_machines/dispute_reject_compensation_restores_dunnable_balance
    """
    customer, invoice, dispute = setup_dispute_under_review(
        invoice_face=60_000, dispute_amount=15_000, reason_code="DUPLICATE"
    )
    validate_success(api.reject_dispute(dispute["id"], ar_manager_headers), 200)
    inv_after = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    assert inv_after["disputed_amount_cents"] == 0
    cust_after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert cust_after["exposure_cents"] == 60_000


def test_dispute_amount_exceeds_balance_rejected(api, ar_manager_headers, collections_agent_headers):
    """PRD §3.4: "The disputed amount must not exceed the invoice's dunnable
    balance — its `balance_cents` minus any existing `disputed_amount_cents` — or
    the request is rejected with `ERR_DISPUTE_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/validations/dispute_amount_exceeds_balance_rejected
    """
    customer = create_customer(name="DE")
    invoice = create_invoice(customer["id"], face_amount_cents=60_000)
    res = api.create_dispute(
        create_dispute_payload(invoice["id"], amount_cents=70_000, reason_code="PRICING"),
        collections_agent_headers,
    )
    validate_error(res, "ERR_DISPUTE_EXCEEDS_BALANCE")

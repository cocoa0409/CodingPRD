"""Compensating-action invariants on post-completion cancellation: the money balance
restored to zero, and the completed-count decremented back.

Queue A (Difficulty) — rule compensating_invariant.
Queue B (Corner) — errors section (no-charge-to-refund).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    setup_schedule_and_account, setup_completed_and_charged, setup_completed_transaction,
    make_account_holder_headers, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]


def test_cancel_after_completion_refund_restores_balance(api):
    """PRD §3.9: "the system creates a REFUND payment for the settled total — which
    restores the account's outstanding_balance_cents to its pre-charge value, the
    compensating invariant that returns that transaction's net contribution to zero"

    Design: Difficulty/compensating_invariant/cancel_after_completion_refund_restores_balance_invariant
    """
    schedule, account = setup_schedule_and_account(
        account_type="RETAIL", state_code="CA",
        schedule_overrides={"use_tax_rate_bps": 625, "title_fee_cents": 2000})
    # TITLE declared 1000000, no trade, no expedite -> total 69000; CHARGE 69000 -> balance 0.
    txn, settled, _payment = setup_completed_and_charged(
        account["id"], "TITLE",
        txn_overrides={"declared_price_cents": 1000000, "trade_in_allowance_cents": 0})
    assert settled["total_cents"] == 69000
    balance_before = get_success_data(api.get_account(account["id"], ADMIN))
    assert balance_before["outstanding_balance_cents"] == 0

    holder = make_account_holder_headers(account["id"])
    cancelled = validate_success(api.cancel_transaction(txn["id"], holder), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    # A REFUND payment of 69000 now exists for this transaction.
    refunds, meta = validate_paginated(api.list_payments(ADMIN, params={
        "transaction_id": txn["id"]}))
    refund_amounts = [p["amount_cents"] for p in refunds if p["kind"] == "REFUND"]
    assert 69000 in refund_amounts

    # CHARGE 69000 then REFUND 69000 -> net contribution 0.
    account_after = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert account_after["outstanding_balance_cents"] == 0


def test_cancel_after_completion_decrements_ytd_completed_count(api):
    """PRD §3.9: "decrements the owning account's ytd_completed_count by one to undo the
    completion's increment"

    Design: Difficulty/compensating_invariant/cancel_after_completion_decrements_ytd_completed_count_invariant
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    # REGISTRATION -> total 13000; complete then CHARGE 13000.
    txn, settled, _payment = setup_completed_and_charged(account["id"], "REGISTRATION")
    after_complete = get_success_data(api.get_account(account["id"], ADMIN))
    assert after_complete["ytd_completed_count"] == 1

    holder = make_account_holder_headers(account["id"])
    cancelled = validate_success(api.cancel_transaction(txn["id"], holder), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    account_after = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert account_after["ytd_completed_count"] == 0


# ─── Corner: errors (no charge to refund) ─────────────────────────────

def test_no_charge_to_refund_on_postcompletion_cancel(api):
    """PRD §3.9: "A COMPLETED transaction may be cancelled only if a CHARGE payment
    exists for it, so that a compensating refund is possible; without such a charge the
    reversal is rejected with ERR_NO_CHARGE_TO_REFUND (HTTP 409)."

    Design: Corner/errors/no_charge_to_refund_on_postcompletion_cancel
    """
    schedule, fleet = setup_schedule_and_account(
        account_type="FLEET", state_code="CA",
        account_overrides={"credit_terms": True, "credit_limit_cents": 100000})
    # FLEET postpaid: completion adds balance with NO CHARGE recorded.
    txn, _sub, _settled = setup_completed_transaction(fleet["id"], "REGISTRATION")

    holder = make_account_holder_headers(fleet["id"])
    res = api.cancel_transaction(txn["id"], holder)
    validate_error(res, "ERR_NO_CHARGE_TO_REFUND", expected_status=409)

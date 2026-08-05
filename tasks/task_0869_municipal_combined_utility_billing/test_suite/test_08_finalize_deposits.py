"""Move-out finalization: final bill generation, deposit settlement waterfall,
refund-on-overage cascade, and the deposit cash-conservation invariant."""
from test_helpers import (
    validate_success, validate_paginated,
    TEST_USERS,
    finalize_payload, assert_deposit_conservation,
    setup_account_with_meter_and_deposit, setup_account_with_deposit_no_meters,
)

BS = TEST_USERS["billing_specialist_headers"]


def _finalize_and_fetch(api, ctx):
    final_bill = validate_success(api.finalize_account(ctx["account"]["id"], finalize_payload(), BS), 201)
    deposits, _ = validate_paginated(api.list_deposits(ctx["account"]["id"], BS))
    deposit = [d for d in deposits if d["id"] == ctx["deposit"]["id"]][0]
    account = validate_success(api.get_account(ctx["account"]["id"], BS))
    return final_bill, deposit, account


# ---------------------------------------------------------------------------
# transitive_cascade / finalize_deposit_refund_cascade_depth3
# ---------------------------------------------------------------------------
def test_finalize_generates_final_bill_and_applies_deposit(api):
    """PRD §3.9: "first a final bill is generated for the account's active meters over that
    closing period, priced exactly as in §3.3; then any still-`ACTIVE` budget-billing plan
    is cancelled with its deferred balance settled into that final bill; then the account's
    `HELD` deposits are settled against the final outstanding balance."
    PRD §3.9: "Applied deposit money is added to the final bill's `amount_paid_cents`".

    Design: Difficulty/transitive_cascade/finalize_deposit_refund_cascade_depth3
    """
    ctx = setup_account_with_meter_and_deposit(api, reading_value=9500, deposit_amount=6000)
    final_bill, deposit, _ = _finalize_and_fetch(api, ctx)
    assert final_bill["total_due_cents"] == 4640
    assert final_bill["amount_paid_cents"] == 4640
    assert deposit["status"] == "APPLIED"


def test_finalize_refunds_deposit_overage_and_finals_account(api):
    """PRD §3.9: "A deposit that contributes any money moves `HELD → APPLIED` with
    `applied_cents` set to the applied portion and `refunded_cents` to the rest".
    PRD §3.9: "Finalization then sets the account's `move_out_date` to the current clock,
    removes the account's meters (`status → REMOVED`), transitions the account to `FINALED`".

    Design: Difficulty/transitive_cascade/finalize_deposit_refund_cascade_depth3
    """
    ctx = setup_account_with_meter_and_deposit(api, reading_value=9500, deposit_amount=6000)
    _, deposit, account = _finalize_and_fetch(api, ctx)
    assert deposit["applied_cents"] == 4640
    assert deposit["refunded_cents"] == 1360
    assert account["status"] == "FINALED"


# ---------------------------------------------------------------------------
# compensating_invariant / deposit_conservation_amount_equals_applied_plus_refunded
# ---------------------------------------------------------------------------
def test_deposit_split_into_applied_and_refunded(api):
    """PRD §3.9: "A deposit that contributes any money moves `HELD → APPLIED` with
    `applied_cents` set to the applied portion and `refunded_cents` to the rest".

    Design: Difficulty/compensating_invariant/deposit_conservation_amount_equals_applied_plus_refunded
    """
    ctx = setup_account_with_meter_and_deposit(api, reading_value=9500, deposit_amount=6000)
    _, deposit, _ = _finalize_and_fetch(api, ctx)
    assert deposit["applied_cents"] == 4640
    assert deposit["refunded_cents"] == 1360


def test_deposit_cash_conservation_invariant(api):
    """PRD §3.9: "In every case a deposit's `amount_cents` equals its `applied_cents` plus
    its `refunded_cents`."

    Design: Difficulty/compensating_invariant/deposit_conservation_amount_equals_applied_plus_refunded
    """
    ctx = setup_account_with_meter_and_deposit(api, reading_value=9500, deposit_amount=6000)
    _, deposit, _ = _finalize_and_fetch(api, ctx)
    assert_deposit_conservation(deposit)
    assert deposit["amount_cents"] == 6000


# ---------------------------------------------------------------------------
# state_machines / deposit_fully_refunded_when_no_balance (corner)
# ---------------------------------------------------------------------------
def test_deposit_fully_refunded_when_final_balance_zero(api):
    """PRD §3.9: "a deposit against a fully satisfied balance moves `HELD → REFUNDED` with
    its whole `amount_cents` refunded and `applied_cents` 0."

    Design: Corner/state_machines/deposit_fully_refunded_when_no_balance
    """
    ctx = setup_account_with_deposit_no_meters(api, deposit_amount=3000)
    _, deposit, _ = _finalize_and_fetch(api, ctx)
    assert deposit["status"] == "REFUNDED"
    assert deposit["refunded_cents"] == 3000
    assert deposit["applied_cents"] == 0

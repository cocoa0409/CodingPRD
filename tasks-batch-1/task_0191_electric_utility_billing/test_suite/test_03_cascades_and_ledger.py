"""Cascade and ledger-conservation compliance: the payment->arrears-clear->
disconnect-cancel->service-revert chain, the void->credit-refund->grant-unexhaust
chain, the payment waterfall, and the credit-pool / account-balance conservation
invariants across reversible operations.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
)
from test_helpers.fixtures import (
    OPERATOR,
    CASEWORKER,
    create_active_tariff,
    open_account,
    add_meter,
    import_reads,
    create_draft_bill,
    issue_bill_with_occ_data,
    pledge_grant,
    setup_issued_bill,
    setup_disconnect_pending,
    setup_assisted_issued_bill,
    pay_account,
    pay_account_data,
    reads_for_2756,
    reads_for_2636,
    _iso,
)



# ===========================================================================
# Queue A — transitive_cascade
# ===========================================================================
def test_payment_clears_arrears_cascades_to_service_active(api):
    """PRD §3.5: "When that recomputation leaves no `ISSUED` or `PARTIALLY_PAID`
    bill past due, the account's `financial_status` returns to `CURRENT` from
    either `DELINQUENT` or `IN_ARREARS`. If the payment clears arrears while a
    scheduled disconnect order is still outstanding — that is, while the account
    is `DISCONNECT_PENDING` — the system additionally returns the account's
    `service_status` to `ACTIVE` and cancels that scheduled disconnect order,
    moving it to `CANCELLED`."

    One trigger (POST /payments 2636) drives a depth-3 cascade: financial
    IN_ARREARS->CURRENT; disconnect order SCHEDULED->CANCELLED; service
    DISCONNECT_PENDING->ACTIVE.

    Design: Difficulty/transitive_cascade/payment_clears_arrears_cascades_cancel_disconnect_revert_service
    """
    scene, order = setup_disconnect_pending()  # 2636 bill, IN_ARREARS, pending
    pay_account_data(scene["account"]["id"], 2636)
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["financial_status"] == "CURRENT", acct["financial_status"]
    assert acct["service_status"] == "ACTIVE", acct["service_status"]
    order_after = get_success_data(api.get_service_order(order["id"], OPERATOR))
    assert order_after["status"] == "CANCELLED", order_after["status"]
    bill_after = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert bill_after["status"] == "PAID", bill_after["status"]


def test_void_refunds_credit_and_unexhausts_grant(api):
    """PRD §3.4: "A void unwinds every ledger effect the issuance applied: it
    decreases the account's `balance_cents` by the bill's `total_due_cents`,
    refunds `net_metering_credit_applied_cents` back into the account's
    `net_metering_credit_balance_cents`, and refunds `assistance_applied_cents`
    back into the source assistance grant's `remaining_cents` (un-exhausting the
    grant if it had been fully consumed)."

    Voiding a budget-free assisted bill (no export so credit refund is 0) drives
    the grant EXHAUSTED->APPLIED and returns the account balance to 0.

    Design: Difficulty/transitive_cascade/void_bill_refunds_credit_then_grant_unexhausts
    """
    scene = setup_assisted_issued_bill(pledged_cents=2000)
    grant_id = scene["grant"]["id"]
    validate_success(api.void_bill(scene["bill"]["id"], OPERATOR), 200)
    grant = get_success_data(api.get_assistance_grant(grant_id, OPERATOR))
    assert grant["remaining_cents"] == 2000, grant["remaining_cents"]
    assert grant["status"] in ("APPLIED", "PLEDGED"), grant["status"]
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["balance_cents"] == 0, acct["balance_cents"]


# ===========================================================================
# Queue A — compensating_invariant
# ===========================================================================
def test_void_conserves_net_metering_credit_pool(api):
    """PRD §3.3: "the account's `net_metering_credit_balance_cents` is debited by
    `net_metering_credit_applied_cents` at issuance, leaving the unused remainder
    banked for next month."
    PRD §3.4: "refunds `net_metering_credit_applied_cents` back into the
    account's `net_metering_credit_balance_cents`"

    With a pre-issue credit balance of 0, issuing a bill (export 2000 -> credit
    20000, applied 96, carryover 19904) then voiding it conserves the pool: the
    balance returns to the full 20000 export credit, none consumed.

    Design: Difficulty/compensating_invariant/void_conserves_net_metering_credit_pool
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], [
        (_iso("2026-01-05", 0), _iso("2026-01-05", 1), 10.0, 2000.0),
    ])
    bill = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    issued = issue_bill_with_occ_data(bill["id"], account["id"])
    assert issued["net_metering_credit_applied_cents"] == 96, \
        issued["net_metering_credit_applied_cents"]
    after_issue = get_success_data(api.get_account(account["id"], OPERATOR))
    assert after_issue["net_metering_credit_balance_cents"] == 19904, \
        after_issue["net_metering_credit_balance_cents"]
    validate_success(api.void_bill(bill["id"], OPERATOR), 200)
    after_void = get_success_data(api.get_account(account["id"], OPERATOR))
    assert after_void["net_metering_credit_balance_cents"] == 20000, \
        after_void["net_metering_credit_balance_cents"]


def test_payment_reverse_conserves_account_balance(api):
    """PRD §2.7: "a payment reduces `balance_cents` by the full payment amount"
    PRD §3.5: "Reversal moves the payment `POSTED → REVERSED`, recomputes
    `amount_paid_cents` on each bill the reversed payment had touched from only
    the remaining posted allocations, and recomputes each affected bill's
    `status` from its new `amount_paid_cents`. Depending on the resulting
    `amount_paid_cents`, a bill may drop from `PAID` to `PARTIALLY_PAID`, from
    `PAID` to `ISSUED`, or from `PARTIALLY_PAID` to `ISSUED`."

    Balance 2756 -> pay 1000 (balance 1756, bill PARTIALLY_PAID) -> reverse
    (balance back to 2756, bill back to ISSUED). Net drift is zero.

    Design: Difficulty/compensating_invariant/payment_reverse_conserves_account_balance
    """
    scene = setup_issued_bill(read_tuples=reads_for_2756())  # actual 2756
    acct0 = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct0["balance_cents"] == 2756, acct0["balance_cents"]
    payment = pay_account_data(scene["account"]["id"], 1000)
    acct1 = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct1["balance_cents"] == 1756, acct1["balance_cents"]
    bill1 = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert bill1["status"] == "PARTIALLY_PAID", bill1["status"]
    validate_success(api.reverse_payment(payment["id"], OPERATOR), 200)
    acct2 = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct2["balance_cents"] == 2756, acct2["balance_cents"]
    bill2 = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert bill2["status"] == "ISSUED", bill2["status"]


# ===========================================================================
# Queue B — calculations (payment waterfall, partial clear)
# ===========================================================================
def test_payment_partial_clear_pays_oldest_leaves_next_issued(api):
    """PRD §3.5: "Allocation follows an oldest-due-first waterfall. The candidate
    bills are the account's bills in `ISSUED` or `PARTIALLY_PAID` status, ordered
    by `due_date` ascending and, where due dates tie, by `created_at` ascending
    (never by `id`). Walking that order, the system computes each bill's
    outstanding amount as its `total_due_cents` minus its current
    `amount_paid_cents`, applies the smaller of the remaining payment and that
    outstanding amount"
    PRD §3.5: "a bill whose `amount_paid_cents` is at least its `total_due_cents`
    becomes `PAID`"

    Two 2636 bills (bill1 due earlier). Paying 2636 fully clears bill1 (PAID),
    leaves bill2 ISSUED, and the account balance drops to 2636.

    Design: Corner/calculations/payment_partial_clear_advances_oldest_unpaid
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], reads_for_2636("2026-01-05"))
    import_reads(meter["id"], reads_for_2636("2026-02-05"))
    bill1 = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    issue_bill_with_occ_data(bill1["id"], account["id"])
    bill2 = create_draft_bill(
        account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
        "2026-03-20T00:00:00Z")
    issue_bill_with_occ_data(bill2["id"], account["id"])
    pay_account_data(account["id"], 2636)
    b1 = get_success_data(api.get_bill(bill1["id"], OPERATOR))
    b2 = get_success_data(api.get_bill(bill2["id"], OPERATOR))
    assert b1["status"] == "PAID", b1["status"]
    assert b2["status"] == "ISSUED", b2["status"]
    acct = get_success_data(api.get_account(account["id"], OPERATOR))
    assert acct["balance_cents"] == 2636, acct["balance_cents"]


# ===========================================================================
# Queue A — second-coverage tests
# ===========================================================================
def test_payment_clearing_arrears_cancels_disconnect_order(api):
    """PRD §3.5: "the system additionally returns the account's `service_status`
    to `ACTIVE` and cancels that scheduled disconnect order, moving it to
    `CANCELLED`."
    PRD §3.6: "When the cancelled order is a `DISCONNECT` and the account is still
    `DISCONNECT_PENDING`, cancelling it reverts the account's service dimension
    back to `ACTIVE`. ... This same disconnect-cancel-and-revert is what the
    payment waterfall triggers automatically when a clearing payment lifts an
    account out of arrears while a disconnect order is still scheduled"

    Focusing on the middle cascade link: the SCHEDULED disconnect ServiceOrder
    raised by the notice is moved to CANCELLED by the clearing payment.

    Design: Difficulty/transitive_cascade/payment_clears_arrears_cascades_cancel_disconnect_revert_service
    """
    scene, order = setup_disconnect_pending()
    before = get_success_data(api.get_service_order(order["id"], OPERATOR))
    assert before["status"] == "SCHEDULED", before["status"]
    pay_account_data(scene["account"]["id"], 2636)
    after = get_success_data(api.get_service_order(order["id"], OPERATOR))
    assert after["status"] == "CANCELLED", after["status"]


def test_void_with_export_credit_refunds_both_credit_and_grant(api):
    """PRD §3.4: "A void unwinds every ledger effect the issuance applied: it
    decreases the account's `balance_cents` by the bill's `total_due_cents`,
    refunds `net_metering_credit_applied_cents` back into the account's
    `net_metering_credit_balance_cents`, and refunds `assistance_applied_cents`
    back into the source assistance grant's `remaining_cents` (un-exhausting the
    grant if it had been fully consumed)."

    Both refund hops on one void: the net-metering credit returns to the account
    bank and the assistance returns to the grant. With a PLEDGED grant and an
    export-bearing read, voiding restores both the credit balance and the grant's
    remaining_cents.

    Design: Difficulty/transitive_cascade/void_bill_refunds_credit_then_grant_unexhausts
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    # OFF_PEAK export read funds the credit bank; the 2756 read set supplies gross.
    import_reads(meter["id"], [
        (_iso("2026-01-05", 0), _iso("2026-01-05", 1), 0.0, 100.0),
    ])
    import_reads(meter["id"], reads_for_2756("2026-01-06"))
    grant = pledge_grant(account["id"], 5000)
    bill = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    issued = issue_bill_with_occ_data(bill["id"], account["id"])
    applied_credit = issued["net_metering_credit_applied_cents"]
    applied_assist = issued["assistance_applied_cents"]
    acct_after_issue = get_success_data(api.get_account(account["id"], OPERATOR))
    grant_after_issue = get_success_data(api.get_assistance_grant(grant["id"], OPERATOR))
    validate_success(api.void_bill(bill["id"], OPERATOR), 200)
    acct_after_void = get_success_data(api.get_account(account["id"], OPERATOR))
    grant_after_void = get_success_data(api.get_assistance_grant(grant["id"], OPERATOR))
    assert acct_after_void["net_metering_credit_balance_cents"] == \
        acct_after_issue["net_metering_credit_balance_cents"] + applied_credit
    assert grant_after_void["remaining_cents"] == \
        grant_after_issue["remaining_cents"] + applied_assist


def test_full_payment_then_reverse_restores_balance_and_paid_status(api):
    """PRD §2.7: "a payment reduces `balance_cents` by the full payment amount"
    PRD §3.5: "Reversal moves the payment `POSTED → REVERSED`, recomputes
    `amount_paid_cents` on each bill the reversed payment had touched from only
    the remaining posted allocations, and recomputes each affected bill's
    `status` from its new `amount_paid_cents`. Depending on the resulting
    `amount_paid_cents`, a bill may drop from `PAID` to `PARTIALLY_PAID`, from
    `PAID` to `ISSUED`, or from `PARTIALLY_PAID` to `ISSUED`."

    A second conservation check using a full clearing payment: balance 2636 -> 0
    on PAID, then reversal restores balance to 2636 and the bill to ISSUED. Net
    drift zero.

    Design: Difficulty/compensating_invariant/payment_reverse_conserves_account_balance
    """
    scene = setup_issued_bill(read_tuples=reads_for_2636())  # actual 2636
    account_id = scene["account"]["id"]
    payment = pay_account_data(account_id, 2636)
    paid = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert paid["status"] == "PAID", paid["status"]
    assert get_success_data(api.get_account(account_id, OPERATOR))["balance_cents"] == 0
    validate_success(api.reverse_payment(payment["id"], OPERATOR), 200)
    acct = get_success_data(api.get_account(account_id, OPERATOR))
    assert acct["balance_cents"] == 2636, acct["balance_cents"]
    reverted = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert reverted["status"] == "ISSUED", reverted["status"]

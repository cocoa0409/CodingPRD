"""Customer-initiated transactions, courtesy-pay floor, and the overdraft/NSF fee tiers
(PRD §3.4–§3.6, §3.10).

Covers queue-A difficulty instances for the courtesy-pay overdraft/NSF dual variant, the
PENDING -> {POSTED, RETURNED, STOPPED} branch fork, the courtesy-floor boundary, and the
single-account ledger conservation, plus queue-B corner instances for the fee daily cap,
amount validation, and immediate/derived balance consistency.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_account_holder_headers,
    make_officer_headers,
    set_clock,
    create_apy_tier,
    open_account,
    open_account_with_deposit,
    open_account_with_courtesy_pay,
    place_stop_payment,
    list_all_fee_assessments,
    list_all_transactions,
    assert_balance_identity,
)
from test_helpers.factories import transaction_payload


def _holder(customer):
    return make_account_holder_headers(customer["id"])


# ===========================================================================
# Queue A — dual_variant_calc / courtesy_pay_overdraft_vs_nsf_variant
# ===========================================================================
def test_courtesy_opted_in_overdraft_posts_with_fee(api):
    """PRD §3.5: "When the account has `courtesy_pay_opted_in` true, the post is
    permitted as long as that post-debit available balance is at least the negative of
    `courtesy_pay_limit_cents`".
    PRD §3.6: "carries a `fee_type` of either `OVERDRAFT` (for a paid overdraft) or
    `NSF` (for a returned item)".
    PRD §3.6: "The first fee-bearing item of the day, ordinal one, is charged three
    thousand cents."

    A 12000 withdrawal against a 10000 opted-in balance POSTS into overdraft: ledger
    10000 - 12000 - 3000(fee) = -5000.

    Design: Difficulty/dual_variant_calc/courtesy_pay_overdraft_vs_nsf_variant
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_courtesy_pay(deposit_cents=10000, limit_cents=50000)
    holder = _holder(cust)
    res = api.create_transaction(
        account["id"], transaction_payload("WITHDRAWAL", 12000), holder
    )
    txn = validate_success(res, 201)
    assert txn["status"] == "POSTED"

    acct_after = validate_success(api.get_account(account["id"], holder), 200)
    assert acct_after["ledger_balance_cents"] == -5000
    assert_balance_identity(acct_after)

    fees = list_all_fee_assessments(account["id"], cust["id"])
    assert len(fees) == 1
    assert fees[0]["fee_type"] == "OVERDRAFT"
    assert fees[0]["fee_amount_cents"] == 3000


def test_courtesy_opted_out_nsf_returns_with_fee(api):
    """PRD §3.5: "When courtesy pay is not opted in, the post is permitted only if the
    post-debit available balance is at least zero. A debit that would breach its
    applicable floor does not post: it transitions `PENDING → RETURNED` with
    `return_reason_code` of `NSF`."
    PRD §3.6: "A fee is itself a `FEE` debit transaction that posts immediately, and it
    can push the account further negative."

    A 12000 withdrawal against a 10000 opted-out balance is RETURNED NSF; the item does
    not post but the 3000 NSF fee posts as a FEE debit: ledger 10000 - 3000 = 7000.

    Design: Difficulty/dual_variant_calc/courtesy_pay_overdraft_vs_nsf_variant
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=10000)
    holder = _holder(cust)
    res = api.create_transaction(
        account["id"], transaction_payload("WITHDRAWAL", 12000), holder
    )
    txn = validate_success(res, 201)
    assert txn["status"] == "RETURNED"
    assert txn["return_reason_code"] == "NSF"

    acct_after = validate_success(api.get_account(account["id"], holder), 200)
    assert acct_after["ledger_balance_cents"] == 7000

    fees = list_all_fee_assessments(account["id"], cust["id"])
    assert len(fees) == 1
    assert fees[0]["fee_type"] == "NSF"
    assert fees[0]["fee_amount_cents"] == 3000


# ===========================================================================
# Queue A — non_linear_state_machine / transaction_branch_posted_returned_stopped
# ===========================================================================
def test_check_debit_matching_active_stop_is_stopped(api):
    """PRD §3.5: "If the transaction is a `CHECK_DEBIT` and there is an `ACTIVE`
    `StopPayment` on the account whose `check_number` matches and whose
    `max_amount_cents` is greater than or equal to the presented `amount_cents`, the
    debit does not post: it transitions `PENDING → STOPPED`, takes `return_reason_code`
    of `STOP_PAYMENT`, has no fee assessed against it, and the matched stop order moves
    `ACTIVE → CONSUMED`."

    Design: Difficulty/non_linear_state_machine/transaction_branch_posted_returned_stopped
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=20000)
    place_stop_payment(account["id"], cust["id"], check_number="5001",
                       max_amount_cents=9000, expires_on="2026-12-31")
    holder = _holder(cust)

    res = api.create_transaction(
        account["id"], transaction_payload("CHECK_DEBIT", 8000, check_number="5001"),
        holder,
    )
    txn = validate_success(res, 201)
    assert txn["status"] == "STOPPED"
    assert txn["return_reason_code"] == "STOP_PAYMENT"

    acct_after = validate_success(api.get_account(account["id"], holder), 200)
    assert acct_after["ledger_balance_cents"] == 20000, "stopped item never posts"

    stops = validate_success(api.list_stop_payments(account["id"], holder), 200)
    matched = [s for s in stops if s["check_number"] == "5001"]
    assert len(matched) == 1
    assert matched[0]["status"] == "CONSUMED"

    fees = list_all_fee_assessments(account["id"], cust["id"])
    assert len(fees) == 0, "stopped item carries no fee"


def test_deposit_posts_and_withdrawal_returns_branches(api):
    """PRD §3.5: "A debit that clears its floor transitions `PENDING → POSTED`".
    PRD §3.5: "A debit that would breach its applicable floor does not post: it
    transitions `PENDING → RETURNED` with `return_reason_code` of `NSF`."

    Distinct branch endpoints of the same machine: a deposit POSTS, an over-floor
    withdrawal RETURNS.

    Design: Difficulty/non_linear_state_machine/transaction_branch_posted_returned_stopped
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    holder = _holder(cust)

    dep = validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 5000), holder),
        201,
    )
    assert dep["status"] == "POSTED"

    wd = validate_success(
        api.create_transaction(account["id"], transaction_payload("WITHDRAWAL", 9000), holder),
        201,
    )
    assert wd["status"] == "RETURNED"
    assert wd["return_reason_code"] == "NSF"


# ===========================================================================
# Queue A — boundary_precision_check / courtesy_floor_exact_vs_one_cent_over
# ===========================================================================
def test_withdrawal_exactly_at_courtesy_floor_posts(api):
    """PRD §3.5: "the post is permitted as long as that post-debit available balance is
    at least the negative of `courtesy_pay_limit_cents` — that is, the available balance
    may dip to, but not below, minus the courtesy-pay limit."

    Ledger 10000, limit 50000 -> floor -50000. A 60000 withdrawal lands post-debit
    available at exactly -50000 (inclusive) so it POSTS; then the tier-1 OVERDRAFT fee
    of 3000 drives ledger to -53000.

    Design: Difficulty/boundary_precision_check/courtesy_floor_exact_vs_one_cent_over
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_courtesy_pay(deposit_cents=10000, limit_cents=50000)
    holder = _holder(cust)
    res = api.create_transaction(
        account["id"], transaction_payload("WITHDRAWAL", 60000), holder
    )
    txn = validate_success(res, 201)
    assert txn["status"] == "POSTED", "post-debit available == -50000 == floor (inclusive)"

    acct_after = validate_success(api.get_account(account["id"], holder), 200)
    assert acct_after["ledger_balance_cents"] == -53000


def test_withdrawal_one_cent_below_courtesy_floor_returns(api):
    """PRD §3.5: "the available balance may dip to, but not below, minus the
    courtesy-pay limit."
    PRD §3.5: "A debit that would breach its applicable floor does not post: it
    transitions `PENDING → RETURNED` with `return_reason_code` of `NSF`."

    Ledger 10000, limit 50000 -> floor -50000. A 60001 withdrawal would land available
    at -50001, one cent below the floor, so it is RETURNED NSF.

    Design: Difficulty/boundary_precision_check/courtesy_floor_exact_vs_one_cent_over
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_courtesy_pay(deposit_cents=10000, limit_cents=50000)
    holder = _holder(cust)
    res = api.create_transaction(
        account["id"], transaction_payload("WITHDRAWAL", 60001), holder
    )
    txn = validate_success(res, 201)
    assert txn["status"] == "RETURNED"
    assert txn["return_reason_code"] == "NSF"


# ===========================================================================
# Queue A — compensating_invariant / deposit_then_equal_withdrawal_conserves_single_ledger
# ===========================================================================
def test_deposit_then_equal_withdrawal_conserves_ledger(api):
    """PRD §3.4: "The `ledger_balance_cents` is the sum of the signed amounts of every
    `POSTED` transaction on the account, where a transaction's sign comes from its
    `direction`: a `CREDIT` contributes its `amount_cents` as a positive, a `DEBIT`
    contributes its `amount_cents` as a negative."

    A 7500 deposit paired with a compensating 7500 withdrawal leaves ledger at its
    starting 10000 with no fee drift.

    Design: Difficulty/compensating_invariant/deposit_then_equal_withdrawal_conserves_single_ledger
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=10000)
    holder = _holder(cust)

    validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 7500), holder), 201
    )
    validate_success(
        api.create_transaction(account["id"], transaction_payload("WITHDRAWAL", 7500), holder), 201
    )

    acct_after = validate_success(api.get_account(account["id"], holder), 200)
    assert acct_after["ledger_balance_cents"] == 10000

    fees = list_all_fee_assessments(account["id"], cust["id"])
    assert len(fees) == 0

    txns = list_all_transactions(account["id"], cust["id"])
    posted = [t for t in txns if t["status"] == "POSTED"]
    assert len(posted) == 3, "initial deposit + the conserving pair, all POSTED"


def test_balanced_pair_preserves_balance_identity(api):
    """PRD §3.4: "The `available_balance_cents` is `ledger_balance_cents` minus
    `hold_total_cents`."

    After a balanced deposit/withdrawal pair with no pending holds, available equals
    ledger and the identity holds.

    Design: Difficulty/compensating_invariant/deposit_then_equal_withdrawal_conserves_single_ledger
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=10000)
    holder = _holder(cust)
    validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 3000), holder), 201
    )
    validate_success(
        api.create_transaction(account["id"], transaction_payload("WITHDRAWAL", 3000), holder), 201
    )
    acct_after = validate_success(api.get_account(account["id"], holder), 200)
    assert acct_after["ledger_balance_cents"] == 10000
    assert acct_after["available_balance_cents"] == 10000
    assert_balance_identity(acct_after)


# ===========================================================================
# Queue B — calculations / fee_tier_daily_cap_fifth_item_zero
# ===========================================================================
def test_fee_tier_daily_cap_fifth_item_is_zero(api):
    """PRD §3.6: "The first fee-bearing item of the day, ordinal one, is charged three
    thousand cents. The second, third, and fourth items — ordinals two through four —
    are each charged thirty-five hundred cents. From the fifth item onward the daily cap
    has been reached and the fee is zero cents".

    Five sequential overdrawing withdrawals yield tier ordinals 1..5 with fees
    3000, 3500, 3500, 3500, 0 (sum 13500).

    Design: Corner/calculations/fee_tier_daily_cap_fifth_item_zero
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_courtesy_pay(deposit_cents=10000, limit_cents=1000000)
    holder = _holder(cust)

    # First overdraw drains the 10000 balance and then 4 more small overdraws.
    api.create_transaction(account["id"], transaction_payload("WITHDRAWAL", 11000), holder)
    for _ in range(4):
        api.create_transaction(account["id"], transaction_payload("WITHDRAWAL", 1000), holder)

    fees = list_all_fee_assessments(account["id"], cust["id"])
    assert len(fees) == 5, f"expected 5 fee rows (ordinals 1..5), got {len(fees)}"
    by_ord = {f["tier_ordinal"]: f for f in fees}
    assert by_ord[1]["fee_amount_cents"] == 3000
    assert by_ord[2]["fee_amount_cents"] == 3500
    assert by_ord[3]["fee_amount_cents"] == 3500
    assert by_ord[4]["fee_amount_cents"] == 3500
    assert by_ord[5]["fee_amount_cents"] == 0
    assert sum(f["fee_amount_cents"] for f in fees) == 13500


# ===========================================================================
# Queue B — validations / negative_transaction_amount_rejected
# ===========================================================================
def test_zero_transaction_amount_rejected(api):
    """PRD §2.9: "a transaction `amount_cents` or an ACH leg `amount_cents` must be a
    strictly positive integer, and an `ApyTier` `annual_rate_bps` must be zero or
    greater; a violation of either is rejected with `ERR_INVALID_AMOUNT` (HTTP 422)."

    Design: Corner/validations/negative_transaction_amount_rejected
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    holder = _holder(cust)
    res = api.create_transaction(account["id"], transaction_payload("DEPOSIT", 0), holder)
    validate_error(res, "ERR_INVALID_AMOUNT", expected_status=422)


# ===========================================================================
# Queue B — entities / account_system_balances_initialize_to_zero
# ===========================================================================
def test_new_account_balances_initialize_to_zero(api):
    """PRD §3.3: "`ledger_balance_cents` initialized to zero".
    PRD §3.4: "The `available_balance_cents` is `ledger_balance_cents` minus
    `hold_total_cents`."
    PRD §3.4: "`od_nsf_items_today`, the count of fee assessments whose `assessed_date`
    equals the current ledger clock date".

    Design: Corner/entities/account_system_balances_initialize_to_zero
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    holder = _holder(cust)
    fresh = validate_success(api.get_account(account["id"], holder), 200)
    assert fresh["ledger_balance_cents"] == 0
    assert fresh["available_balance_cents"] == 0
    assert fresh["od_nsf_items_today"] == 0
    assert fresh["hold_total_cents"] == 0


# ===========================================================================
# Queue B — cross_cutting (derived_field_reconciliation) /
#           derived_available_balance_reflects_pending_hold
# ===========================================================================
def test_available_equals_ledger_with_no_pending_holds(api):
    """PRD §3.4: "The `hold_total_cents` is the sum of `amount_cents` across all
    transactions that are still `PENDING` and have `direction` `DEBIT`".
    PRD §3.4: "The `available_balance_cents` is `ledger_balance_cents` minus
    `hold_total_cents`."

    A single posted deposit and no pending debits: hold_total is 0 and available equals
    ledger.

    Design: Corner/cross_cutting_complexity_layers/derived_available_balance_reflects_pending_hold
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account_with_deposit(deposit_cents=8000)
    holder = _holder(cust)
    fresh = validate_success(api.get_account(account["id"], holder), 200)
    assert fresh["ledger_balance_cents"] == 8000
    assert fresh["hold_total_cents"] == 0
    assert fresh["available_balance_cents"] == 8000


# ===========================================================================
# Queue B — consistency_model / immediate_balance_visible_in_same_response
# ===========================================================================
def test_deposit_effect_immediately_visible(api):
    """PRD §2.7: "derived account balances and downstream resource states are always
    brought back into agreement immediately, within the same operation that disturbed
    them."
    PRD §3.4: "The `ledger_balance_cents` is the sum of the signed amounts of every
    `POSTED` transaction on the account".

    Design: Corner/consistency_model/immediate_balance_visible_in_same_response
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account()
    holder = _holder(cust)
    validate_success(
        api.create_transaction(account["id"], transaction_payload("DEPOSIT", 12345), holder), 201
    )
    fresh = validate_success(api.get_account(account["id"], holder), 200)
    assert fresh["ledger_balance_cents"] == 12345

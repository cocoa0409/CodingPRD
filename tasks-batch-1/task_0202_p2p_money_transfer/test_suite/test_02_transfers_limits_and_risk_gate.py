"""Send-limit pre-flight, the risk fork, and settlement/hold routing.

Queue A: combinatorial_formula/transfer_limit_nested_min_across_two_windows,
non_linear_state_machine/transfer_branching_fork_sent_to_held_vs_settled,
boundary_precision_check/large_amount_threshold_ge_on_transfers,
resource_temporal_overlap/account_daily_window_aggregate_capacity_overlap,
priority_pair_validation_conflict/daily_limit_constraint_beats_insufficient_funds_fiscal.
Queue B: calculations (unverified cap boundary), validations (self transfer),
state_machines (freeze blocks send), errors (unverified above cap -> hold),
consistency (settled balances visible same request).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_account_holder_headers,
    create_account,
    make_recipient_verified,
    setup_settled_transfer_pair,
    set_clock,
    seed_credit,
    freeze_account,
    send_transfer,
    create_settled_transfer,
    create_transfer_payload,
    assert_transfer,
)


# ===========================================================================
# Queue A — combinatorial_formula / transfer_limit_nested_min_across_two_windows
# ===========================================================================
def test_weekly_window_binding_rejects_over_effective_headroom(api):
    """PRD §3.3: "The daily remaining headroom is `daily_send_limit_cents` minus
    daily usage, and the weekly remaining headroom is `weekly_send_limit_cents`
    minus weekly usage. The effective headroom is the smaller of the two."
    PRD §3.3: "if instead the weekly remaining is strictly less than the daily
    remaining, the weekly window is binding and the rejection is
    `ERR_WEEKLY_LIMIT_EXCEEDED`."

    Weekly limit 120000 with 100000 used this week (daily window empty): weekly
    remaining 20000 binds; a 25000 send is rejected with the weekly error.

    Design: Difficulty/combinatorial_formula/transfer_limit_nested_min_across_two_windows
    """
    sender = create_account(funded_cents=500000, daily_send_limit_cents=250000,
                            weekly_send_limit_cents=120000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    set_clock("2026-06-02T00:00:00.000Z")
    validate_success(send_transfer(sender["id"], recipient["id"], 100000), 201)
    set_clock("2026-06-08T00:00:00.000Z")
    res = send_transfer(sender["id"], recipient["id"], 25000)
    validate_error(res, ApiErrorId.ERR_WEEKLY_LIMIT_EXCEEDED.value)


def test_send_exactly_at_effective_headroom_allowed(api):
    """PRD §3.3: "A send of an amount exactly equal to the effective headroom is
    allowed; a send of even one cent more is rejected."

    With weekly remaining 20000 binding, a send of exactly 20000 is allowed.

    Design: Difficulty/combinatorial_formula/transfer_limit_nested_min_across_two_windows
    """
    sender = create_account(funded_cents=500000, daily_send_limit_cents=250000,
                            weekly_send_limit_cents=120000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    set_clock("2026-06-02T00:00:00.000Z")
    validate_success(send_transfer(sender["id"], recipient["id"], 100000), 201)
    set_clock("2026-06-08T00:00:00.000Z")
    res = send_transfer(sender["id"], recipient["id"], 20000)
    transfer = validate_success(res, 201)
    assert transfer["status"] == "SETTLED"


# ===========================================================================
# Queue A — non_linear_state_machine / transfer_branching_fork_sent_to_held_vs_settled
# ===========================================================================
def test_large_amount_routes_to_held_recipient_not_credited(api):
    """PRD §3.3: "if the `amount_cents` is at least 100000 cents (1,000.00 USD),
    the transfer is held with reason `LARGE_AMOUNT`; note this threshold is
    inclusive, so exactly 100000 cents holds."
    PRD §3.3: "the transfer's `risk_flagged` is set true, a `RiskHold` is created
    referencing this transfer with the gate's `reason_code` and a `status` of
    `PENDING_REVIEW`, and the transfer's `hold_id` is set to it."
    PRD §3.3: "but the recipient is **not** yet credited; the sender's
    `available_balance_cents` drops and `held_balance_cents` rises by `amount_cents`."

    A 100000c send routes to HELD with risk_flagged true; recipient balance stays 0.

    Design: Difficulty/non_linear_state_machine/transfer_branching_fork_sent_to_held_vs_settled
    """
    sender = create_account(funded_cents=500000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    transfer = validate_success(send_transfer(sender["id"], recipient["id"], 100000), 201)
    assert transfer["status"] == "HELD"
    assert transfer["risk_flagged"] is True
    rec = validate_success(api.get_account(recipient["id"], make_account_holder_headers(recipient["id"])), 200)
    assert rec["available_balance_cents"] == 0


def test_sub_threshold_send_settles_and_credits_recipient(api):
    """PRD §3.3: "If none of the three rules match, the transfer settles."
    PRD §3.3: "a `CREDIT` ledger entry for `amount_cents` is posted to the
    recipient and a `DEBIT` ledger entry for `amount_cents` is posted to the
    sender ... and both parties' `available_balance_cents` are recomputed."

    A 99999c send (below the LARGE threshold) settles and credits the recipient.

    Design: Difficulty/non_linear_state_machine/transfer_branching_fork_sent_to_held_vs_settled
    """
    sender = create_account(funded_cents=500000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    transfer = validate_success(send_transfer(sender["id"], recipient["id"], 99999), 201)
    assert transfer["status"] == "SETTLED"
    rec = validate_success(api.get_account(recipient["id"], make_account_holder_headers(recipient["id"])), 200)
    assert rec["available_balance_cents"] == 99999


# ===========================================================================
# Queue A — boundary_precision_check / large_amount_threshold_ge_on_transfers
# ===========================================================================
class TestLargeAmountThresholdBoundary:
    """PRD §3.3: the LARGE_AMOUNT rule uses an inclusive >= 100000 threshold."""

    def test_one_below_threshold_settles(self, api):
        """PRD §3.3: "if the `amount_cents` is at least 100000 cents (1,000.00 USD),
        the transfer is held with reason `LARGE_AMOUNT`; note this threshold is
        inclusive, so exactly 100000 cents holds."

        99999c is below the inclusive boundary -> SETTLED.

        Design: Difficulty/boundary_precision_check/large_amount_threshold_ge_on_transfers
        """
        sender = create_account(funded_cents=500000)
        recipient = create_account()
        make_recipient_verified(recipient["id"])
        t = validate_success(send_transfer(sender["id"], recipient["id"], 99999), 201)
        assert t["status"] == "SETTLED"

    def test_exactly_at_threshold_holds(self, api):
        """PRD §3.3: "note this threshold is inclusive, so exactly 100000 cents holds."

        Exactly 100000c is at the inclusive boundary -> HELD.

        Design: Difficulty/boundary_precision_check/large_amount_threshold_ge_on_transfers
        """
        sender = create_account(funded_cents=500000)
        recipient = create_account()
        make_recipient_verified(recipient["id"])
        t = validate_success(send_transfer(sender["id"], recipient["id"], 100000), 201)
        assert t["status"] == "HELD"


# ===========================================================================
# Queue A — resource_temporal_overlap / account_daily_window_aggregate_capacity_overlap
# ===========================================================================
def test_two_sends_in_same_daily_window_aggregate_against_ceiling(api):
    """PRD §3.3: "The daily usage is the sum of `amount_cents` over the sender's
    transfers in `SENT`, `HELD`, or `SETTLED` status whose `created_at` falls
    within the last 24 hours"
    PRD §3.3: "if the daily remaining is less than or equal to the weekly
    remaining, the daily window is binding and the rejection is
    `ERR_DAILY_LIMIT_EXCEEDED`"

    200000 sent at 00:00 plus a 60000 attempt at 12:00 aggregate to 260000 against
    the 250000 daily ceiling within the same 24h window -> rejected.

    Design: Difficulty/resource_temporal_overlap/account_daily_window_aggregate_capacity_overlap
    """
    sender = create_account(funded_cents=500000, daily_send_limit_cents=250000,
                            weekly_send_limit_cents=5000000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    set_clock("2026-06-01T00:00:00.000Z")
    validate_success(send_transfer(sender["id"], recipient["id"], 200000), 201)
    set_clock("2026-06-01T12:00:00.000Z")
    res = send_transfer(sender["id"], recipient["id"], 60000)
    validate_error(res, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)


def test_second_send_after_daily_window_rolls_off_allowed(api):
    """PRD §3.3: "whose `created_at` falls within the last 24 hours"

    A first send 25h before the second falls outside the daily window, so it does
    not aggregate and the second send within the daily ceiling is allowed.

    Design: Difficulty/resource_temporal_overlap/account_daily_window_aggregate_capacity_overlap
    """
    sender = create_account(funded_cents=500000, daily_send_limit_cents=250000,
                            weekly_send_limit_cents=5000000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    set_clock("2026-06-01T00:00:00.000Z")
    validate_success(send_transfer(sender["id"], recipient["id"], 200000), 201)
    set_clock("2026-06-02T01:00:00.000Z")  # 25h later, first send rolled off the daily window
    res = send_transfer(sender["id"], recipient["id"], 60000)
    t = validate_success(res, 201)
    assert t["status"] == "SETTLED"


# ===========================================================================
# Queue A — priority_pair_validation_conflict / daily_limit_constraint_beats_insufficient_funds_fiscal
# ===========================================================================
def test_daily_limit_error_wins_over_insufficient_funds(api):
    """PRD §2.5: "they are evaluated in a fixed priority order, and the first
    failing check determines the error returned. The order is: ... (13) the daily
    send limit, surfacing `ERR_DAILY_LIMIT_EXCEEDED`; ... (15) sufficiency of
    funds, surfacing `ERR_INSUFFICIENT_FUNDS`"

    A 300000 send exceeds both the 250000 daily limit (p13) and the 200000 balance
    (p15); the lower-priority-number daily check wins.

    Design: Difficulty/priority_pair_validation_conflict/daily_limit_constraint_beats_insufficient_funds_fiscal
    """
    set_clock("2026-06-01T00:00:00.000Z")
    sender = create_account(funded_cents=200000, daily_send_limit_cents=250000,
                            weekly_send_limit_cents=1000000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    res = send_transfer(sender["id"], recipient["id"], 300000)
    validate_error(res, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)


def test_insufficient_funds_alone_when_within_limit(api):
    """PRD §3.3: "the sender must also have an `available_balance_cents` at least
    equal to `amount_cents`, or the send is rejected with `ERR_INSUFFICIENT_FUNDS`."

    A send within the daily/weekly limits but above the balance fails with the
    funds error in isolation (no limit conflict).

    Design: Difficulty/priority_pair_validation_conflict/daily_limit_constraint_beats_insufficient_funds_fiscal
    """
    set_clock("2026-06-01T00:00:00.000Z")
    sender = create_account(funded_cents=10000, daily_send_limit_cents=250000,
                            weekly_send_limit_cents=1000000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    res = send_transfer(sender["id"], recipient["id"], 50000)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


# ===========================================================================
# Queue B — calculations: unverified recipient cap boundary at 5000 settles
# ===========================================================================
def test_unverified_recipient_cap_boundary_settles_at_5000(api):
    """PRD §3.3: "if the recipient's `is_recipient_verified` is false and the
    `amount_cents` is strictly greater than 5000 cents (50.00 USD), the transfer is
    held with reason `UNVERIFIED_RECIPIENT`; this cap is exclusive, so a send of
    exactly 5000 cents to an unverified recipient does not hold."

    Exactly 5000c to a never-verified recipient settles (exclusive cap).

    Design: Corner/calculations/unverified_recipient_cap_boundary_at_5000_settles
    """
    sender = create_account(funded_cents=50000)
    recipient = create_account()  # never verified
    t = validate_success(send_transfer(sender["id"], recipient["id"], 5000), 201)
    assert t["status"] == "SETTLED"
    rec = validate_success(api.get_account(recipient["id"], make_account_holder_headers(recipient["id"])), 200)
    assert rec["available_balance_cents"] == 5000


# ===========================================================================
# Queue B — errors: unverified recipient above cap routes to hold
# ===========================================================================
def test_unverified_recipient_above_cap_routes_to_hold(api):
    """PRD §3.3: "if the recipient's `is_recipient_verified` is false and the
    `amount_cents` is strictly greater than 5000 cents (50.00 USD), the transfer is
    held with reason `UNVERIFIED_RECIPIENT`"

    A 6000c send (> 5000) to a never-verified recipient is held with reason
    UNVERIFIED_RECIPIENT; the recipient is not credited.

    Design: Corner/errors/unverified_recipient_above_cap_routes_to_hold
    """
    sender = create_account(funded_cents=50000)
    recipient = create_account()
    transfer = validate_success(send_transfer(sender["id"], recipient["id"], 6000), 201)
    assert transfer["status"] == "HELD"
    hold = validate_success(api.get_risk_hold(transfer["hold_id"], make_account_holder_headers(sender["id"])), 200)
    assert hold["reason_code"] == "UNVERIFIED_RECIPIENT"
    rec = validate_success(api.get_account(recipient["id"], make_account_holder_headers(recipient["id"])), 200)
    assert rec["available_balance_cents"] == 0


# ===========================================================================
# Queue B — validations: self-transfer rejected
# ===========================================================================
def test_self_transfer_rejected(api):
    """PRD §3.3: "the recipient must be a different account than the sender (a
    self-send is rejected with `ERR_SELF_TRANSFER`)"

    sender_account_id == recipient_account_id is rejected.

    Design: Corner/validations/self_transfer_rejected
    """
    acct = create_account(funded_cents=10000)
    res = api.create_transfer(
        create_transfer_payload(acct["id"], acct["id"], 1000),
        make_account_holder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SELF_TRANSFER.value)


# ===========================================================================
# Queue B — state_machines: freeze blocks subsequent send
# ===========================================================================
def test_frozen_sender_cannot_send(api):
    """PRD §2.10: "While an account is `FROZEN`, it cannot send money ... Any such
    attempt against a frozen account is rejected with `ERR_ACCOUNT_FROZEN`
    (HTTP 409)."

    A FROZEN sender's transfer is rejected with ERR_ACCOUNT_FROZEN.

    Design: Corner/state_machines/freeze_account_blocks_subsequent_send
    """
    sender = create_account(funded_cents=100000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    freeze_account(sender["id"])
    res = send_transfer(sender["id"], recipient["id"], 1000)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_FROZEN.value)


# ===========================================================================
# Queue B — consistency_model: settled balances visible in same request
# ===========================================================================
def test_settled_transfer_balances_visible_immediately(api):
    """PRD §2.6: "Both balances default to 0 at account creation and are recomputed
    atomically whenever a posting touches the account."
    PRD §3.3: "both parties' `available_balance_cents` are recomputed. `SETTLED`
    is terminal."

    After a 2500 settle from a 10000 sender, an immediate GET shows sender 7500 and
    recipient 2500.

    Design: Corner/consistency_model/settled_transfer_balances_visible_same_request
    """
    sender, recipient, transfer = setup_settled_transfer_pair(amount_cents=2500, sender_funded=10000)
    assert transfer["status"] == "SETTLED"
    s = validate_success(api.get_account(sender["id"], make_account_holder_headers(sender["id"])), 200)
    r = validate_success(api.get_account(recipient["id"], make_account_holder_headers(recipient["id"])), 200)
    assert s["available_balance_cents"] == 7500
    assert r["available_balance_cents"] == 2500

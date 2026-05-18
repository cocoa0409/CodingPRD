"""Account lifecycle transitions and their cascades — PRD §3.1.

Coverage:
- ACTIVE -> CLOSED appends FORFEIT, zeroes balance, FORFEITS unfinished
  signup bonus.
- Re-close of CLOSED account -> ERR_ACCOUNT_CLOSED.
- ACTIVE -> DELINQUENT reverses PENDING PointsTransfer rows.
- DELINQUENT account earns zero points on subsequent posts.
- DELINQUENT -> ACTIVE re-enables earn going forward.
- DELINQUENT account does not lose its tier (parallel state dimensions).
- close with PENDING transfer blocked (precondition: no PENDING).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    clear_account_delinquency,
    close_account,
    create_points_transfer_payload,
    find_ledger_entries,
    get_ledger,
    initiate_points_transfer,
    make_cardholder_headers,
    mark_account_delinquent,
    post_purchase,
    re_get_account,
    register_partner,
    setup_account_on_gold,
    setup_account_with_balance_via_signup,
    setup_account_with_fixed_bonus_category,
    setup_closed_account,
    setup_delinquent_account,
    setup_platinum_with_high_balance,
    validate_error,
)


# ===========================================================================
# ACTIVE -> CLOSED forfeiture cascade — PRD §3.1
# ===========================================================================
class TestCloseCascade:

    def test_close_appends_forfeit_row_zero_balance_and_forfeits_bonus(
        self, api,
    ):
        """PRD §3.1: "The transition from ACTIVE to CLOSED first
        appends a single FORFEIT ledger entry whose delta_points is the
        negation of the current points_balance, then recomputes
        points_balance to zero, and finally — if signup_bonus_state is
        anything other than AWARDED — advances signup_bonus_state to
        FORFEITED."

        Claim: a fresh ACTIVE account with points_balance=N and
        signup_bonus_state=PENDING, when closed, emits one FORFEIT row
        with delta_points==-N, zeroes balance, and transitions
        signup_bonus_state to FORFEITED.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        # Spend below signup threshold so signup_bonus_state stays
        # PENDING and there's a small EARN balance to forfeit.
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=20_000,
        )
        acc_pre_close = re_get_account(acc["id"])
        balance_pre_close = acc_pre_close["points_balance"]
        assert acc_pre_close["signup_bonus_state"] == "PENDING"
        # Close.
        closed = close_account(
            account_id=acc["id"], cardholder_id=ch["id"],
        )
        assert closed["lifecycle_state"] == "CLOSED"
        assert closed["points_balance"] == 0
        assert closed["signup_bonus_state"] == "FORFEITED"
        ledger = get_ledger(acc["id"])
        forfeit_rows = find_ledger_entries(
            ledger, entry_type="FORFEIT",
        )
        assert len(forfeit_rows) == 1
        assert forfeit_rows[0]["delta_points"] == -balance_pre_close

    def test_reclose_returns_account_closed(self, api):
        """PRD §3.1: "an attempt to close an already-closed account is
        rejected with ERR_ACCOUNT_CLOSED as well".

        Claim: a second POST /accounts/{id}/close ->
        ERR_ACCOUNT_CLOSED.
        """
        ch, closed = setup_closed_account()
        resp = api.close_account(
            closed["id"], None, make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED.value)

    def test_close_with_pending_transfer_blocked(self, api):
        """PRD §3.1: "Account closure is initiated by either the
        cardholder themselves or by a PlatformAdmin, and it requires
        that the account's lifecycle_state is currently ACTIVE and that
        no PointsTransfer belonging to the account is in PENDING
        status."

        Claim: close with at least one PENDING PointsTransfer is
        rejected with ERR_INVALID_STATE.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        resp = api.close_account(
            acc["id"], None, make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# ACTIVE -> DELINQUENT cascade — PRD §3.1
# ===========================================================================
class TestDelinquencyCascade:

    def test_delinquency_reverses_pending_transfers(self, api):
        """PRD §3.1: "A PlatformAdmin may also mark an ACTIVE account
        DELINQUENT. This transition reverses every PointsTransfer on
        the account whose status is PENDING (cascade hop one); for each
        reversal, a TRANSFER_REVERSE ledger entry is appended whose
        delta_points equals the positive points_debited of the original
        transfer (cascade hop two); the account's points_balance is
        then recomputed by re-summing the ledger (cascade hop three)."

        Claim: marking an account DELINQUENT auto-reverses each PENDING
        transfer; ledger gains TRANSFER_REVERSE rows whose delta_points
        is positive points_debited; the resulting points_balance equals
        the pre-transfer balance.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        balance_before_transfer = acc["points_balance"]
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        # Mark delinquent — should auto-reverse the pending transfer.
        mark_account_delinquent(acc["id"])
        ledger = get_ledger(acc["id"])
        rev_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_REVERSE",
            source_entity_id=transfer["id"],
        )
        assert len(rev_rows) == 1
        assert rev_rows[0]["delta_points"] == transfer["points_debited"]
        acc_after = re_get_account(acc["id"])
        assert acc_after["lifecycle_state"] == "DELINQUENT"
        assert acc_after["points_balance"] == balance_before_transfer, (
            f"after delinquency cascade, balance must match "
            f"pre-transfer ({balance_before_transfer}); got "
            f"{acc_after['points_balance']}"
        )

    def test_delinquent_earn_is_zero(self, api):
        """PRD §3.4 step six: "if the account's lifecycle_state at
        posted_at is anything other than ACTIVE, points_provisional is
        forced to zero regardless of the earlier steps".
        PRD §3.1: "While the account remains DELINQUENT, every purchase
        post earns zero points (see §3.4)".

        Claim: a PURCHASE on a DELINQUENT account writes
        points_provisional == 0.
        """
        ch, deli, cat = setup_delinquent_account()
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=deli["id"],
            category_id=cat["id"], amount_cents=10_000,
        )
        assert txn["points_provisional"] == 0

    def test_clear_delinquency_re_enables_earn_going_forward(self, api):
        """PRD §3.1: "The matching DELINQUENT-to-ACTIVE clear-delinquency transition simply re-enables earn going forward; it never backfills earn for transactions posted while the account
        was delinquent."

        Claim: after clear-delinquency, a NEW PURCHASE earns at the
        usual rate, but the prior DELINQUENT-time PURCHASE remains at
        points_provisional == 0.
        """
        ch, deli, cat = setup_delinquent_account()
        deli_txn = post_purchase(
            cardholder_id=ch["id"], account_id=deli["id"],
            category_id=cat["id"], amount_cents=10_000,
        )
        assert deli_txn["points_provisional"] == 0
        clear_account_delinquency(deli["id"])
        new_txn = post_purchase(
            cardholder_id=ch["id"], account_id=deli["id"],
            category_id=cat["id"], amount_cents=10_000,
        )
        # Active again -> floor(10000 * 500 / 10000) = 500 at 5%.
        assert new_txn["points_provisional"] == 500


# ===========================================================================
# Parallel state dimensions — PRD §2.10 / §3.1
# ===========================================================================
class TestParallelStateDimensions:

    def test_delinquency_does_not_change_tier(self, api):
        """PRD §2.10: "The tier is materially distinct from the
        lifecycle_state dimension: a DELINQUENT account retains its
        tier, and a tier upgrade does not change the lifecycle."

        Claim: after STANDARD->GOLD upgrade, marking the account
        DELINQUENT leaves spending_tier == GOLD.
        """
        ch, gold, _cat = setup_account_on_gold()
        assert gold["spending_tier"] == "GOLD"
        deli = mark_account_delinquent(gold["id"])
        assert deli["lifecycle_state"] == "DELINQUENT"
        assert deli["spending_tier"] == "GOLD", (
            f"DELINQUENT must retain prior tier; got "
            f"{deli['spending_tier']}"
        )

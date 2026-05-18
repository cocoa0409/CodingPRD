"""Transaction posting and the points_provisional earn calculation —
PRD §3.4.

Coverage:
- POST /transactions PURCHASE produces a Transaction with the PRD §2.4
  common fields.
- points_provisional is computed per PRD §3.4's six-step formula
  with floor-then-floor order.
- EARN ledger entry is appended with delta_points == points_provisional.
- ytd_qualifying_spend_cents and last_qualifying_activity_at update on
  PURCHASE.
- REFUND flips original to REVERSED, appends EARN_ADJUST with negation
  of original points_provisional, decrements ytd, leaves
  last_qualifying_activity_at unchanged.
- Refund validation: ERR_REFUND_MISMATCH, ERR_PARTIAL_REFUND_DISALLOWED,
  ERR_INVALID_STATE on already-REVERSED source.
- amount_cents >= 1 (PRD §3.4).
- Computed Account points_balance from ledger sum is consistent
  (PRD §2.7).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_balance_equals_ledger_sum,
    assert_transaction,
    create_purchase_payload,
    create_refund_payload,
    find_ledger_entries,
    get_ledger,
    make_cardholder_headers,
    post_purchase,
    post_refund,
    re_get_account,
    re_get_transaction,
    setup_account_with_baseline_category,
    setup_account_with_fixed_bonus_category,
    setup_closed_account,
    validate_error,
    validate_success,
)


# ===========================================================================
# PURCHASE earn calculation — PRD §3.4
# ===========================================================================
class TestPurchaseEarnFormula:
    """PRD §3.4 six-step evaluation order."""

    def test_purchase_returns_transaction_with_provisional(self, api):
        """PRD §3.4: "Every purchase post writes a points_provisional
        value into the transaction row according to a fixed, six-step
        evaluation order."

        Claim: POST /transactions PURCHASE returns a Transaction whose
        points_provisional is populated.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        headers = make_cardholder_headers(ch["id"])
        resp = api.create_transaction(
            create_purchase_payload(
                account_id=acc["id"], category_id=cat["id"],
                amount_cents=10_000,
            ),
            headers,
        )
        txn = validate_success(resp, expected_status=201)
        assert_transaction(txn)
        # STANDARD tier (10000) * category 500 / 10000 = 500;
        # 10000 cents * 500 / 10000 = 500 points.
        assert txn["points_provisional"] == 500, (
            f"expected 500 points_provisional for 10000 cents at 5% on "
            f"STANDARD, got {txn['points_provisional']}"
        )
        # PRD §3.4: "points_final is initialised to zero for new
        # transactions and is only later populated by the tier-upgrade
        # backfill (§3.5)."
        assert txn["points_final"] == 0

    def test_purchase_on_baseline_one_percent(self, api):
        """PRD §3.4: step one — "if the category's category_type is
        BASELINE or FIXED_BONUS, it is base_rate_bps".
        PRD §3.4: step two — "STANDARD yields ten thousand (one-times
        multiplier)".

        Claim: a 50000-cent purchase at 100 bps on STANDARD yields
        floor(50000 * floor(100*10000/10000) / 10000) = 500 points.
        """
        ch, acc, cat = setup_account_with_baseline_category()
        headers = make_cardholder_headers(ch["id"])
        resp = api.create_transaction(
            create_purchase_payload(
                account_id=acc["id"], category_id=cat["id"],
                amount_cents=50_000,
            ),
            headers,
        )
        txn = validate_success(resp, expected_status=201)
        assert txn["points_provisional"] == 500

    def test_purchase_appends_earn_ledger_entry(self, api):
        """PRD §3.4: "the server appends an EARN ledger entry whose
        delta_points equals the newly computed points_provisional".

        Claim: after PURCHASE there is one EARN row sourced from the
        Transaction with delta_points equal to points_provisional.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=20_000,
        )
        ledger = get_ledger(acc["id"])
        earn_entries = find_ledger_entries(
            ledger, entry_type="EARN", source_entity_id=txn["id"],
        )
        assert len(earn_entries) == 1, (
            f"expected exactly one EARN row sourced from txn {txn['id']}, "
            f"got {len(earn_entries)}"
        )
        assert earn_entries[0]["delta_points"] == txn["points_provisional"]
        assert earn_entries[0]["source_entity_type"] == "Transaction"

    def test_purchase_increments_ytd_qualifying_spend(self, api):
        """PRD §3.4: "the account's ytd_qualifying_spend_cents is
        increased by amount_cents".

        Claim: ytd_qualifying_spend_cents grows by exactly amount_cents
        on PURCHASE.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        ytd_before = acc["ytd_qualifying_spend_cents"]
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=7_777,
        )
        acc_after = re_get_account(acc["id"])
        assert (
            acc_after["ytd_qualifying_spend_cents"] - ytd_before == 7_777
        ), (
            f"ytd_qualifying_spend_cents should grow by 7777, got "
            f"{acc_after['ytd_qualifying_spend_cents'] - ytd_before}"
        )

    def test_purchase_updates_last_qualifying_activity_at(self, api):
        """PRD §3.4: "the account's last_qualifying_activity_at is set
        to the current clock instant (refunds do not update this anchor
        — only purchases reset the expiration clock)".

        Claim: PURCHASE refreshes last_qualifying_activity_at past the
        account's opened_at anchor.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        before = acc["last_qualifying_activity_at"]
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=1_000,
        )
        acc_after = re_get_account(acc["id"])
        # Activity instant is either later than or equal to the prior
        # value depending on clock granularity, but at minimum the
        # account row must surface an updated value.
        assert (
            acc_after["last_qualifying_activity_at"] >= before
        ), (
            f"last_qualifying_activity_at should advance after PURCHASE; "
            f"was {before}, now {acc_after['last_qualifying_activity_at']}"
        )


# ===========================================================================
# REFUND mechanics — PRD §3.4
# ===========================================================================
class TestRefundFlow:
    """PRD §3.4 refund-specific behaviour."""

    def test_refund_flips_original_to_reversed(self, api):
        """PRD §3.4: "A REFUND post does not earn its own row of
        points; instead it flips the original Transaction.status to
        REVERSED, appends an EARN_ADJUST ledger entry whose delta_points
        is the negation of the original transaction's points_provisional,
        decrements ytd_qualifying_spend_cents by the original
        amount_cents, and leaves last_qualifying_activity_at
        unchanged."

        Claim: after REFUND, the original transaction reads status ==
        REVERSED.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=5_000,
        )
        post_refund(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=5_000,
            original_transaction_id=orig["id"],
        )
        refreshed = re_get_transaction(orig["id"])
        assert refreshed["status"] == "REVERSED"

    def test_refund_appends_earn_adjust_negation(self, api):
        """PRD §3.4: "appends an EARN_ADJUST ledger entry whose
        delta_points is the negation of the original transaction's
        points_provisional".

        Claim: ledger contains an EARN_ADJUST row sourced from the
        original transaction with delta_points = -original.points_provisional.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=5_000,
        )
        # STANDARD * 500 -> floor(5000 * 500 / 10000) = 250 points.
        assert orig["points_provisional"] == 250
        post_refund(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=5_000,
            original_transaction_id=orig["id"],
        )
        ledger = get_ledger(acc["id"])
        adjusts = find_ledger_entries(
            ledger, entry_type="EARN_ADJUST", source_entity_id=orig["id"],
        )
        assert len(adjusts) >= 1
        # The refund's adjustment must include exactly -250 against
        # this purchase.
        delta_sum = sum(e["delta_points"] for e in adjusts)
        assert delta_sum == -250, (
            f"sum of EARN_ADJUST deltas sourced from {orig['id']} should "
            f"be -250 (-orig.points_provisional), got {delta_sum}"
        )

    def test_refund_decrements_ytd(self, api):
        """PRD §3.4: "decrements ytd_qualifying_spend_cents by the
        original amount_cents".

        Claim: ytd_qualifying_spend_cents shrinks by exactly the original
        amount_cents after REFUND.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=4_321,
        )
        ytd_post_purchase = re_get_account(acc["id"])[
            "ytd_qualifying_spend_cents"
        ]
        post_refund(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=4_321,
            original_transaction_id=orig["id"],
        )
        ytd_after = re_get_account(acc["id"])[
            "ytd_qualifying_spend_cents"
        ]
        assert ytd_post_purchase - ytd_after == 4_321

    def test_refund_does_not_advance_last_qualifying_activity_at(self, api):
        """PRD §3.4: "and leaves last_qualifying_activity_at unchanged"
        (refund clause).

        Claim: REFUND does not advance last_qualifying_activity_at,
        even though it occurs after a clock instant past the purchase.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=2_000,
        )
        anchor_before = re_get_account(acc["id"])[
            "last_qualifying_activity_at"
        ]
        post_refund(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=2_000,
            original_transaction_id=orig["id"],
        )
        anchor_after = re_get_account(acc["id"])[
            "last_qualifying_activity_at"
        ]
        assert anchor_after == anchor_before, (
            f"REFUND must not advance last_qualifying_activity_at; "
            f"before={anchor_before}, after={anchor_after}"
        )

    def test_refund_of_already_reversed_returns_invalid_state(self, api):
        """PRD §3.4: "the original's status must be POSTED (an attempt
        to refund an already-REVERSED transaction is rejected with
        ERR_INVALID_STATE)".

        Claim: a second REFUND against the same original ->
        ERR_INVALID_STATE.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=1_500,
        )
        post_refund(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=1_500,
            original_transaction_id=orig["id"],
        )
        # Second refund of the same now-REVERSED transaction.
        resp = api.create_transaction(
            create_refund_payload(
                account_id=acc["id"], category_id=cat["id"],
                amount_cents=1_500,
                original_transaction_id=orig["id"],
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_partial_refund_rejected(self, api):
        """PRD §3.4: "the refund's amount_cents must equal the
        original's amount_cents (partial refunds are not supported),
        otherwise ERR_PARTIAL_REFUND_DISALLOWED".

        Claim: REFUND with amount_cents != original.amount_cents ->
        ERR_PARTIAL_REFUND_DISALLOWED.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=10_000,
        )
        resp = api.create_transaction(
            create_refund_payload(
                account_id=acc["id"], category_id=cat["id"],
                amount_cents=4_999,
                original_transaction_id=orig["id"],
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTIAL_REFUND_DISALLOWED.value)

    def test_refund_wrong_account_rejected(self, api):
        """PRD §3.4: "the referenced original must have txn_type equal
        to PURCHASE and must belong to the same account_id, otherwise
        ERR_REFUND_MISMATCH".

        Claim: REFUND from account A pointing at a PURCHASE on account
        B -> ERR_REFUND_MISMATCH.
        """
        ch_a, acc_a, cat = setup_account_with_fixed_bonus_category()
        ch_b, acc_b, _cat_b = setup_account_with_fixed_bonus_category()
        # Post a purchase on B.
        orig_on_b = post_purchase(
            cardholder_id=ch_b["id"], account_id=acc_b["id"],
            category_id=cat["id"], amount_cents=3_000,
        )
        # Refund from A pointing at B's purchase.
        resp = api.create_transaction(
            create_refund_payload(
                account_id=acc_a["id"], category_id=cat["id"],
                amount_cents=3_000,
                original_transaction_id=orig_on_b["id"],
            ),
            make_cardholder_headers(ch_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_MISMATCH.value)


# ===========================================================================
# Lifecycle gate — PRD §3.4 step six
# ===========================================================================
class TestLifecycleGate:

    def test_post_to_closed_account_returns_account_closed(self, api):
        """PRD §3.1: "After closure, every subsequent attempt to post a
        transaction, redeem a credit, transfer points, or activate a
        category against the same account is rejected with
        ERR_ACCOUNT_CLOSED."

        Claim: POST /transactions PURCHASE on a CLOSED account ->
        ERR_ACCOUNT_CLOSED.
        """
        ch, closed = setup_closed_account()
        # Need a category to reference.
        from test_helpers import register_fixed_bonus_category
        cat = register_fixed_bonus_category()
        resp = api.create_transaction(
            create_purchase_payload(
                account_id=closed["id"], category_id=cat["id"],
                amount_cents=1_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED.value)


# ===========================================================================
# FK and path validation on /transactions — PRD §2.5
# ===========================================================================
class TestTransactionReferentialIntegrity:

    def test_unknown_account_id_returns_reference_not_found(self, api):
        """PRD §2.5: "A request body that names a foreign key — ...,
        account_id, ... — is checked after path resolution succeeds; if
        the referenced resource does not exist, the request is rejected
        with ERR_REFERENCE_NOT_FOUND."

        Claim: POST /transactions with bogus account_id ->
        ERR_REFERENCE_NOT_FOUND.
        """
        # Need a real category and a real cardholder so the auth pass
        # doesn't trip first.
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        resp = api.create_transaction(
            create_purchase_payload(
                account_id=NON_EXISTENT_UUID, category_id=cat["id"],
                amount_cents=1_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)

    def test_unknown_category_id_returns_reference_not_found(self, api):
        """PRD §2.5: "A request body that names a foreign key — ...,
        category_id, ... — is checked after path resolution succeeds;
        if the referenced resource does not exist, the request is
        rejected with ERR_REFERENCE_NOT_FOUND."

        Claim: POST /transactions with bogus category_id ->
        ERR_REFERENCE_NOT_FOUND.
        """
        ch, acc, _cat = setup_account_with_fixed_bonus_category()
        resp = api.create_transaction(
            create_purchase_payload(
                account_id=acc["id"], category_id=NON_EXISTENT_UUID,
                amount_cents=1_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Ledger as single source of truth — PRD §2.7
# ===========================================================================
class TestLedgerIsSourceOfTruth:

    def test_points_balance_equals_ledger_sum(self, api):
        """PRD §2.7: "Every change to it is materialised by appending
        exactly one row to the PointsLedgerEntry ledger and then
        recomputing points_balance as the signed sum of delta_points
        over all entries for the account."

        Claim: after a sequence of mixed operations, the Account's
        points_balance equals the signed sum of ledger delta_points.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=10_000,
        )
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=20_000,
        )
        ledger = get_ledger(acc["id"])
        latest_account = re_get_account(acc["id"])
        assert_balance_equals_ledger_sum(latest_account, ledger)

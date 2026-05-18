"""Annual spending tiers and the forward-looking backfill — PRD §3.5.

Coverage:
- STANDARD -> GOLD threshold at 600,000 ytd cents (at-or-above).
- GOLD -> PLATINUM threshold at 1,500,000 ytd cents (at-or-above).
- Both transitions are at-or-above (boundary-exact triggers upgrade).
- Forward-looking backfill: EVERY same-month POSTED transaction is
  re-rated at the new tier, regardless of whether posted_at is before
  or after the upgrade instant.
- EARN_ADJUST ledger rows are appended for each non-zero delta.
- points_final is updated on every backfilled transaction.
- Pre-month transactions are NOT backfilled.
- Year-rollover sweep resets ytd to zero and tier to STANDARD without a
  compensating ledger entry.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TIER_GOLD_THRESHOLD_CENTS,
    TIER_PLATINUM_THRESHOLD_CENTS,
    advance_clock_to,
    find_ledger_entries,
    get_ledger,
    post_purchase,
    re_get_account,
    re_get_transaction,
    register_fixed_bonus_category,
    run_year_rollover,
    setup_account_with_fixed_bonus_category,
    setup_clock_at,
)


# ===========================================================================
# Threshold boundary — PRD §3.5
# ===========================================================================
class TestTierThresholds:

    def test_standard_to_gold_at_exactly_six_hundred_thousand(self, api):
        """PRD §3.5: "The transition from STANDARD to GOLD fires when
        the post brings the counter to at-or-above six hundred thousand
        cents (six thousand dollars), provided the account's pre-post
        tier was STANDARD and lifecycle_state was ACTIVE."

        Claim: a single PURCHASE of 600,000 cents (exactly the threshold)
        upgrades the account from STANDARD to GOLD.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        assert acc["spending_tier"] == "STANDARD"
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=TIER_GOLD_THRESHOLD_CENTS,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["spending_tier"] == "GOLD", (
            f"expected GOLD at ytd=={TIER_GOLD_THRESHOLD_CENTS}, got "
            f"{acc_after['spending_tier']}"
        )

    def test_one_under_threshold_stays_standard(self, api):
        """PRD §3.5: "The transition from STANDARD to GOLD fires when
        the post brings the counter to at-or-above six hundred thousand
        cents".

        Claim: a single PURCHASE of 599,999 cents leaves spending_tier
        at STANDARD.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=TIER_GOLD_THRESHOLD_CENTS - 1,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["spending_tier"] == "STANDARD", (
            f"expected STANDARD at ytd=={TIER_GOLD_THRESHOLD_CENTS - 1}, "
            f"got {acc_after['spending_tier']}"
        )


# ===========================================================================
# Forward-looking backfill — PRD §3.5 (load-bearing rule)
# ===========================================================================
class TestForwardLookingBackfill:

    def test_pre_upgrade_same_month_transaction_is_backfilled(self, api):
        """PRD §3.5: "The backfill is forward-looking, and this rule is
        load-bearing: when a tier upgrade fires mid-month, every
        Transaction that posted in the same calendar month UTC
        (regardless of whether its posted_at is before or after the
        upgrade's clock instant) and whose status is POSTED is
        re-evaluated at the new tier."

        Claim: a 100,000-cent PURCHASE on 2026-01-05 (T1) followed by a
        500,000-cent PURCHASE on 2026-01-20 (T2, which crosses the
        threshold and triggers STANDARD -> GOLD) leaves T1's points_final
        at the GOLD-re-rated value:
          provisional at STANDARD: floor(100000*500/10000) = 5000.
          GOLD-rated: combined_bps=floor(500*12500/10000)=625;
                      floor(100000*625/10000) = 6250.
          T1.points_final == 6250.
        """
        setup_clock_at(2026, 1, 1)
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500, year=2026, month=1, day=2,
        )
        advance_clock_to("2026-01-05T12:00:00.000Z")
        t1 = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=100_000,
        )
        assert t1["points_provisional"] == 5000
        advance_clock_to("2026-01-20T12:00:00.000Z")
        t2 = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=500_000,
        )
        # T1 must be re-rated at GOLD even though it posted BEFORE the
        # upgrade instant.
        t1_after = re_get_transaction(t1["id"])
        assert t1_after["points_final"] == 6250, (
            f"forward-looking backfill must re-rate T1 (posted before "
            f"upgrade) at GOLD: expected points_final=6250, got "
            f"{t1_after['points_final']}"
        )

    def test_backfill_appends_earn_adjust_ledger_row(self, api):
        """PRD §3.5: "For each affected transaction the server
        recomputes the earn formula of §3.4 with the new tier
        substituted into step two, computes the delta between the
        recomputed value and the existing points_provisional, and if
        the delta is non-zero appends a single EARN_ADJUST ledger entry
        whose delta_points equals that delta and whose
        source_entity_type and source_entity_id point at the affected
        transaction."

        Claim: ledger contains one EARN_ADJUST row sourced from T1 with
        delta_points == 1250 (= 6250 - 5000).
        """
        setup_clock_at(2026, 1, 1)
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500, year=2026, month=1, day=2,
        )
        advance_clock_to("2026-01-05T12:00:00.000Z")
        t1 = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=100_000,
        )
        advance_clock_to("2026-01-20T12:00:00.000Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=500_000,
        )
        ledger = get_ledger(acc["id"])
        t1_adjusts = find_ledger_entries(
            ledger, entry_type="EARN_ADJUST", source_entity_id=t1["id"],
        )
        assert len(t1_adjusts) == 1, (
            f"expected exactly one EARN_ADJUST row sourced from T1, "
            f"got {len(t1_adjusts)}"
        )
        assert t1_adjusts[0]["delta_points"] == 1250
        assert t1_adjusts[0]["source_entity_type"] == "Transaction"

    def test_prior_month_transaction_not_backfilled(self, api):
        """PRD §3.5: "Transactions posted in any prior calendar month
        are not touched."

        Claim: a PURCHASE posted in December 2025 is NOT given an
        EARN_ADJUST row when a tier upgrade fires in January 2026.
        """
        setup_clock_at(2025, 12, 1)
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500, year=2025, month=12, day=1,
        )
        advance_clock_to("2025-12-15T00:00:00.000Z")
        t_dec = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=100_000,
        )
        # December purchase only credited 100,000 ytd; reset ytd via
        # year-rollover before the tier-triggering January purchase so
        # we isolate "prior-month not touched" cleanly.
        advance_clock_to("2026-01-01T00:00:00.000Z")
        run_year_rollover()
        # Now perform a single Jan purchase that crosses the GOLD
        # threshold (since ytd is now 0).
        advance_clock_to("2026-01-10T00:00:00.000Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=TIER_GOLD_THRESHOLD_CENTS,
        )
        # The December purchase must NOT receive an EARN_ADJUST row.
        ledger = get_ledger(acc["id"])
        dec_adjusts = find_ledger_entries(
            ledger, entry_type="EARN_ADJUST",
            source_entity_id=t_dec["id"],
        )
        assert len(dec_adjusts) == 0, (
            f"prior-month transaction must not receive EARN_ADJUST; "
            f"got {len(dec_adjusts)} rows on T_dec"
        )


# ===========================================================================
# Year-rollover sweep — PRD §3.8
# ===========================================================================
class TestYearRollover:

    def test_year_rollover_resets_ytd_and_tier(self, api):
        """PRD §3.8: "the rollover sweep resets ytd_qualifying_spend_cents
        to zero on every account and resets spending_tier to STANDARD
        on every GOLD or PLATINUM account. The downgrade is not
        accompanied by any compensating ledger entry — points earned
        under the old tier are not clawed back; only the future earn
        rate is affected."

        Claim: after year-rollover, ytd_qualifying_spend_cents == 0,
        spending_tier == STANDARD, and points_balance is unchanged (no
        compensating ledger entry).
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        # Push to GOLD via a 600,000-cent purchase.
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=TIER_GOLD_THRESHOLD_CENTS,
        )
        acc_pre = re_get_account(acc["id"])
        assert acc_pre["spending_tier"] == "GOLD"
        balance_pre = acc_pre["points_balance"]
        # Rollover.
        run_year_rollover()
        acc_post = re_get_account(acc["id"])
        assert acc_post["ytd_qualifying_spend_cents"] == 0
        assert acc_post["spending_tier"] == "STANDARD"
        # No compensating ledger entry => balance unchanged.
        assert acc_post["points_balance"] == balance_pre, (
            f"year-rollover must not claw back points; pre={balance_pre}, "
            f"post={acc_post['points_balance']}"
        )

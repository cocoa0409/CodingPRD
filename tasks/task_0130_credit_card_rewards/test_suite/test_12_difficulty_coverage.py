"""Difficulty-coverage tests — mandatory priority queue.

Each instance in the difficulty-design index is covered by at least two
dedicated tests tagged with `# difficulty: <rule_id>/<instance.name>`.
Tests cite the PRD sentence that states the underlying rule, not the
difficulty-design entry itself.

Instances covered:

1. dual_variant_calc/provisional_vs_final_earn_on_transaction
2. dual_variant_calc/points_first_vs_amount_first_redemption
3. combinatorial_formula/tiered_category_activation_combined_rate
4. combinatorial_formula/nested_floor_order_in_combined_bps_then_points
5. non_linear_state_machine/account_delinquency_cycle
6. non_linear_state_machine/account_parallel_lifecycle_and_tier_dimensions
7. transitive_cascade/close_account_three_hop_cascade
8. transitive_cascade/tier_upgrade_two_hop_backfill_cascade
9. priority_pair_validation_conflict/state_vs_fiscal_close_then_insufficient
10. priority_pair_validation_conflict/referential_vs_constraint_refund_mismatch_and_partial
11. boundary_precision_check/signup_bonus_exact_min_spend_boundary
12. boundary_precision_check/transfer_increment_zero_and_partial_multiple_boundary
13. cross_entity_state_dependency/points_transfer_blocked_by_account_lifecycle
14. cross_entity_state_dependency/quarterly_activation_blocked_by_category_type
15. resource_temporal_overlap/signup_window_half_open_at_deadline
16. resource_temporal_overlap/quarterly_activation_uniqueness_per_quarter
17. compensating_invariant/refund_preserves_net_points_invariant
18. compensating_invariant/transfer_reverse_preserves_balance_invariant
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    MIN_REDEMPTION_POINTS,
    SIGNUP_MIN_SPEND_CENTS,
    TIER_GOLD_THRESHOLD_CENTS,
    activate_category,
    advance_clock_to,
    api_client,
    clear_account_delinquency,
    close_account,
    create_activation_payload,
    create_cardholder_and_account,
    create_points_first_redemption_payload,
    create_points_transfer_payload,
    create_purchase_payload,
    create_refund_payload,
    find_ledger_entries,
    get_ledger,
    initiate_points_transfer,
    make_cardholder_headers,
    mark_account_delinquent,
    post_purchase,
    post_refund,
    re_get_account,
    re_get_transaction,
    register_baseline_category,
    register_fixed_bonus_category,
    register_partner,
    register_rotating_category,
    setup_account_on_gold,
    setup_account_on_platinum,
    setup_account_with_balance_via_signup,
    setup_account_with_fixed_bonus_category,
    setup_account_with_rotating_category,
    setup_clock_at,
    setup_closed_account,
    setup_platinum_with_high_balance,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    # ----- Instance: provisional_vs_final_earn_on_transaction -----

    def test_forward_looking_backfill_re_rates_pre_upgrade_transaction(
        self, api,
    ):
        """PRD §3.5: "The backfill is forward-looking, and this rule is
        load-bearing: when a tier upgrade fires mid-month, every
        Transaction that posted in the same calendar month UTC
        (regardless of whether its posted_at is before or after the
        upgrade's clock instant) and whose status is POSTED is
        re-evaluated at the new tier."

        Claim: T1 posted at 2026-01-05 (STANDARD) gets points_final
        re-evaluated under GOLD after T2 posted at 2026-01-20 crosses
        the STANDARD->GOLD threshold; points_provisional remains 5000
        and points_final becomes 6250.

        # difficulty: dual_variant_calc/provisional_vs_final_earn_on_transaction
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
        assert t1["points_provisional"] == 5_000
        advance_clock_to("2026-01-20T12:00:00.000Z")
        t2 = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=500_000,
        )
        t1_after = re_get_transaction(t1["id"])
        # Provisional is the value at posted_at — unchanged.
        assert t1_after["points_provisional"] == 5_000
        # Final is the forward-looking GOLD re-rating.
        assert t1_after["points_final"] == 6_250

    def test_t2_provisional_at_standard_then_final_at_gold(self, api):
        """PRD §3.4 step two: "Step two selects the tier multiplier in
        basis points by reading the account's spending_tier at
        posted_at: STANDARD yields ten thousand (one-times multiplier),
        GOLD yields twelve thousand five hundred (one-and-a-quarter
        times)".
        PRD §3.5: "The backfill is forward-looking, and this rule is
        load-bearing: when a tier upgrade fires mid-month, every
        Transaction that posted in the same calendar month UTC
        (regardless of whether its posted_at is before or after the
        upgrade's clock instant) and whose status is POSTED is
        re-evaluated at the new tier."

        Claim: T2's points_provisional is computed at STANDARD (the
        pre-upgrade tier read at posted_at) as 25,000, and its
        points_final is re-rated at GOLD as 31,250 by the same-month
        backfill — even though T2 itself caused the upgrade. The
        EARN_ADJUST row sourced from T2 has delta_points = +6250.

        # difficulty: dual_variant_calc/provisional_vs_final_earn_on_transaction
        """
        setup_clock_at(2026, 1, 1)
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500, year=2026, month=1, day=2,
        )
        advance_clock_to("2026-01-05T12:00:00.000Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=100_000,
        )
        advance_clock_to("2026-01-20T12:00:00.000Z")
        t2 = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=500_000,
        )
        # T2 read tier at posted_at -> STANDARD; floor(500000*500/10000)
        # = 25000.
        assert t2["points_provisional"] == 25_000
        t2_after = re_get_transaction(t2["id"])
        # Backfilled at GOLD: combined_bps=625; floor(500000*625/10000)
        # = 31250.
        assert t2_after["points_final"] == 31_250
        ledger = get_ledger(acc["id"])
        t2_adjusts = find_ledger_entries(
            ledger, entry_type="EARN_ADJUST",
            source_entity_id=t2["id"],
        )
        assert len(t2_adjusts) == 1
        assert t2_adjusts[0]["delta_points"] == 6_250

    # ----- Instance: points_first_vs_amount_first_redemption -----

    def test_amount_first_on_platinum_at_3149_costs_2520_points(self, api):
        """PRD §3.6: "For AMOUNT_FIRST, the server records
        credit_amount_cents equal to requested_amount_cents exactly and
        computes points_debited as requested_amount_cents multiplied by
        the tier's points-per-dollar figure and divided by one hundred,
        with the ceiling taken — the cents are exact, and any sub-point
        residue is rounded up so that the system is never under-charged
        points."

        Claim: 3149-cent AMOUNT_FIRST on PLATINUM (80 points/dollar) ->
        points_debited = ceil(3149 * 80 / 100) = ceil(2519.2) = 2520;
        credit_amount_cents == 3149 exactly. Both sides are at-or-above
        the PRD §3.6 minimum of 2500.

        # difficulty: dual_variant_calc/points_first_vs_amount_first_redemption
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        from test_helpers import redeem_amount_first
        credit = redeem_amount_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_amount_cents=3_149,
        )
        assert credit["points_debited"] == 2_520
        assert credit["credit_amount_cents"] == 3_149

    def test_points_first_2520_on_platinum_yields_3150_cents(self, api):
        """PRD §3.6: "For POINTS_FIRST, the server records
        points_debited equal to requested_points and computes
        credit_amount_cents as requested_points multiplied by one
        hundred and divided by the tier's points-per-dollar figure,
        with the floor taken — the points are spent in full, the cents
        are the dependent value, and any sub-cent residue is forfeit
        to the system."

        Claim: 2520 points POINTS_FIRST on PLATINUM (80 points/dollar) ->
        credit_amount_cents = floor(2520 * 100 / 80) = floor(3150.0) =
        3150; points_debited == 2520. Different from the AMOUNT_FIRST
        round-trip at 3149 cents — proving the two modes are not
        inverse at unaligned cent boundaries. requested_points stays
        at-or-above the PRD §3.6 minimum of 2500.

        # difficulty: dual_variant_calc/points_first_vs_amount_first_redemption
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        from test_helpers import redeem_points_first
        credit = redeem_points_first(
            cardholder_id=ch["id"], account_id=acc["id"],
            requested_points=2_520,
        )
        assert credit["points_debited"] == 2_520
        assert credit["credit_amount_cents"] == 3_150


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    # ----- Instance: tiered_category_activation_combined_rate -----

    def test_rotating_unactivated_on_gold_uses_fallback_one_percent(
        self, api,
    ):
        """PRD §3.4 step one: "if the category is ROTATING_QUARTERLY,
        the server looks for a QuarterlyActivation belonging to this
        account_id and category_id whose quarter_label matches the
        quarter of posted_at, ... and whose status is ACTIVATED — if
        such an activation exists, the category rate is base_rate_bps,
        otherwise the category rate falls back to the platform fallback
        of one hundred basis points (one percent)."
        PRD §3.4 step two: "GOLD yields twelve thousand five hundred
        (one-and-a-quarter times)".

        Claim: on GOLD, a 20,000-cent PURCHASE against a ROTATING
        category with NO activation -> floor(20000 *
        floor(100*12500/10000) / 10000) = floor(20000 * 125 / 10000) =
        250 points.

        # difficulty: combinatorial_formula/tiered_category_activation_combined_rate
        """
        # Need GOLD account and a ROTATING category. Reuse the GOLD
        # bootstrap then add a rotating category and post against it.
        ch, gold, _bonus_cat = setup_account_on_gold(rate_bps=500)
        rot = register_rotating_category(base_rate_bps=500)
        advance_clock_to("2026-04-15T12:00:00.000Z")
        # Don't activate — fallback to 1%.
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=gold["id"],
            category_id=rot["id"], amount_cents=20_000,
        )
        assert txn["points_provisional"] == 250

    def test_rotating_activated_on_gold_uses_declared_rate(self, api):
        """PRD §3.4 step one: "if such an activation exists, the
        category rate is base_rate_bps".
        PRD §3.4 step two: "GOLD yields twelve thousand five hundred
        (one-and-a-quarter times)".

        Claim: on GOLD, a 20,000-cent PURCHASE against a ROTATING
        category WITH active QuarterlyActivation -> combined_bps =
        floor(500*12500/10000) = 625; points = floor(20000*625/10000) =
        1250 points. Tests three inputs simultaneously: category state,
        activation existence, tier multiplier.

        # difficulty: combinatorial_formula/tiered_category_activation_combined_rate
        """
        ch, gold, _bonus_cat = setup_account_on_gold(rate_bps=500)
        rot = register_rotating_category(base_rate_bps=500)
        advance_clock_to("2026-04-15T12:00:00.000Z")
        activate_category(
            cardholder_id=ch["id"], account_id=gold["id"],
            category_id=rot["id"], quarter_label="2026Q2",
        )
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=gold["id"],
            category_id=rot["id"], amount_cents=20_000,
        )
        assert txn["points_provisional"] == 1_250

    # ----- Instance: nested_floor_order_in_combined_bps_then_points -----

    def test_floor_then_floor_order_on_platinum_yields_997(self, api):
        """PRD §3.4 step four: "Step four collapses the category rate
        and tier multiplier into a single combined_bps by multiplying
        them together and dividing by ten thousand, taking the floor
        of the result before any cents are involved."
        PRD §3.4 step five: "Step five computes points_provisional as
        the product of amount_cents and combined_bps, divided by ten
        thousand, again with the floor taken."
        PRD §3.4: "The order matters: flooring is applied at the
        combined_bps step before multiplying by amount_cents, and again
        at the final cents-to-points step."

        Claim: PLATINUM (15000 mult) * category 333 bps * 19999 cents
        with floor-then-floor: combined_bps = floor(333*15000/10000) =
        floor(499.5) = 499; points = floor(19999*499/10000) =
        floor(997.9501) = 997.

        # difficulty: combinatorial_formula/nested_floor_order_in_combined_bps_then_points
        """
        ch, acc, _cat = setup_account_on_platinum(rate_bps=500)
        odd_cat = register_fixed_bonus_category(base_rate_bps=333)
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=odd_cat["id"], amount_cents=19_999,
        )
        assert txn["points_provisional"] == 997

    def test_floor_then_floor_order_rejects_single_floor_alternative(
        self, api,
    ):
        """PRD §3.4: "No half-up rounding is ever applied to earn
        computation."
        PRD §3.4: "The order matters: flooring is applied at the
        combined_bps step before multiplying by amount_cents, and again
        at the final cents-to-points step."

        Claim: an implementation that defers flooring (single floor
        over the full product, e.g. floor(19999*333*15000/100000000) =
        998) is wrong. The pinned formula yields 997, not 998 — the
        difference between the two is the distinguishing assertion.

        # difficulty: combinatorial_formula/nested_floor_order_in_combined_bps_then_points
        """
        ch, acc, _cat = setup_account_on_platinum(rate_bps=500)
        odd_cat = register_fixed_bonus_category(base_rate_bps=333)
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=odd_cat["id"], amount_cents=19_999,
        )
        assert txn["points_provisional"] != 998, (
            f"single-floor alternative would yield 998; the pinned "
            f"floor-then-floor formula must produce 997. Got "
            f"{txn['points_provisional']}."
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    # ----- Instance: account_delinquency_cycle -----

    def test_delinquency_cycle_preserves_reversal(self, api):
        """PRD §3.1: "A PlatformAdmin may also mark an ACTIVE account
        DELINQUENT. This transition reverses every PointsTransfer on
        the account whose status is PENDING (cascade hop one); for each
        reversal, a TRANSFER_REVERSE ledger entry is appended whose
        delta_points equals the positive points_debited of the original
        transfer (cascade hop two); the account's points_balance is
        then recomputed by re-summing the ledger (cascade hop three)."
        PRD §3.1: "The matching DELINQUENT-to-ACTIVE clear-delinquency transition simply re-enables earn going forward; it never backfills earn for transactions posted while the account was delinquent."

        Claim: after ACTIVE -> DELINQUENT -> ACTIVE cycle, the auto-
        reversed PointsTransfer remains REVERSED (not re-issued) and
        the ledger contains TRANSFER_DEBIT(-X) followed by
        TRANSFER_REVERSE(+X) summing to net zero.

        # difficulty: non_linear_state_machine/account_delinquency_cycle
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        mark_account_delinquent(acc["id"])
        cleared = clear_account_delinquency(acc["id"])
        assert cleared["lifecycle_state"] == "ACTIVE"
        # The transfer must remain REVERSED — clearing delinquency does
        # not re-issue.
        ledger = get_ledger(acc["id"])
        debit_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_DEBIT",
            source_entity_id=transfer["id"],
        )
        rev_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_REVERSE",
            source_entity_id=transfer["id"],
        )
        assert len(debit_rows) == 1
        assert len(rev_rows) == 1
        net = sum(
            e["delta_points"] for e in debit_rows + rev_rows
        )
        assert net == 0, (
            f"TRANSFER_DEBIT(-X) + TRANSFER_REVERSE(+X) must sum to "
            f"zero; got net = {net}"
        )

    def test_active_restored_after_cycle(self, api):
        """PRD §3.1: "The matching DELINQUENT-to-ACTIVE clear-delinquency transition simply re-enables earn going forward; it never backfills earn for transactions posted while the account was delinquent."

        Claim: lifecycle_state returns to ACTIVE after the cycle, and a
        subsequent PURCHASE earns at the normal rate.

        # difficulty: non_linear_state_machine/account_delinquency_cycle
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        mark_account_delinquent(acc["id"])
        cleared = clear_account_delinquency(acc["id"])
        assert cleared["lifecycle_state"] == "ACTIVE"
        # New purchase under ACTIVE earns normally.
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=10_000,
        )
        assert txn["points_provisional"] == 500

    # ----- Instance: account_parallel_lifecycle_and_tier_dimensions ----

    def test_delinquent_account_keeps_gold_tier(self, api):
        """PRD §2.10: "Every Account carries a parallel state dimension
        spending_tier whose value is one of STANDARD, GOLD, or
        PLATINUM. The tier is materially distinct from the
        lifecycle_state dimension: a DELINQUENT account retains its
        tier, and a tier upgrade does not change the lifecycle."

        Claim: an account on GOLD that is marked DELINQUENT has
        lifecycle_state==DELINQUENT AND spending_tier==GOLD
        simultaneously.

        # difficulty: non_linear_state_machine/account_parallel_lifecycle_and_tier_dimensions
        """
        ch, gold, _cat = setup_account_on_gold(rate_bps=500)
        deli = mark_account_delinquent(gold["id"])
        assert deli["lifecycle_state"] == "DELINQUENT"
        assert deli["spending_tier"] == "GOLD"

    def test_tier_upgrade_does_not_change_lifecycle_state(self, api):
        """PRD §2.10: "a DELINQUENT account retains its tier, and a
        tier upgrade does not change the lifecycle."

        Claim: when a STANDARD/ACTIVE account is upgraded to GOLD by
        crossing the ytd threshold, lifecycle_state remains ACTIVE.

        # difficulty: non_linear_state_machine/account_parallel_lifecycle_and_tier_dimensions
        """
        ch, gold, _cat = setup_account_on_gold(rate_bps=500)
        assert gold["spending_tier"] == "GOLD"
        assert gold["lifecycle_state"] == "ACTIVE", (
            f"tier upgrade must not change lifecycle_state; got "
            f"{gold['lifecycle_state']}"
        )


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    # ----- Instance: close_account_three_hop_cascade -----

    def test_close_three_hop_cascade_terminal_state(self, api):
        """PRD §3.1: "The transition from ACTIVE to CLOSED first
        appends a single FORFEIT ledger entry whose delta_points is the
        negation of the current points_balance, then recomputes
        points_balance to zero, and finally — if signup_bonus_state is
        anything other than AWARDED — advances signup_bonus_state to
        FORFEITED."

        Claim: hop 1 lifecycle_state==CLOSED; hop 2 FORFEIT ledger row;
        hop 3 points_balance==0 AND signup_bonus_state==FORFEITED.

        # difficulty: transitive_cascade/close_account_three_hop_cascade
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        # Spend below signup threshold so signup_bonus_state stays
        # PENDING and there's a balance to forfeit.
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=20_000,
        )
        before = re_get_account(acc["id"])
        assert before["signup_bonus_state"] == "PENDING"
        balance_pre = before["points_balance"]
        closed = close_account(
            account_id=acc["id"], cardholder_id=ch["id"],
        )
        # Hop 1.
        assert closed["lifecycle_state"] == "CLOSED"
        # Hop 2 — FORFEIT row of -balance_pre.
        ledger = get_ledger(acc["id"])
        forfeit_rows = find_ledger_entries(
            ledger, entry_type="FORFEIT",
        )
        assert len(forfeit_rows) == 1
        assert forfeit_rows[0]["delta_points"] == -balance_pre
        # Hop 3 — balance==0 and signup_bonus_state==FORFEITED.
        assert closed["points_balance"] == 0
        assert closed["signup_bonus_state"] == "FORFEITED"

    def test_close_does_not_forfeit_awarded_bonus(self, api):
        """PRD §3.1: "if signup_bonus_state is anything other than
        AWARDED — advances signup_bonus_state to FORFEITED."

        Claim: if signup_bonus_state was AWARDED before close (i.e.,
        the cardholder had qualified), close does NOT transition it
        to FORFEITED — it remains AWARDED.

        # difficulty: transitive_cascade/close_account_three_hop_cascade
        """
        ch, acc, _cat = setup_account_with_balance_via_signup()
        # The signup bonus is awarded by the helper's 300,000-cent
        # purchase.
        assert acc["signup_bonus_state"] == "AWARDED"
        closed = close_account(
            account_id=acc["id"], cardholder_id=ch["id"],
        )
        assert closed["lifecycle_state"] == "CLOSED"
        # AWARDED bonus must not transition to FORFEITED.
        assert closed["signup_bonus_state"] == "AWARDED"

    # ----- Instance: tier_upgrade_two_hop_backfill_cascade -----

    def test_tier_upgrade_emits_earn_adjust_and_recomputes_balance(
        self, api,
    ):
        """PRD §3.5: "Both transitions update spending_tier on the
        account effective for subsequent posts and then trigger a
        current-month backfill cascade."
        PRD §3.5: "if the delta is non-zero appends a single
        EARN_ADJUST ledger entry whose delta_points equals that delta
        ... After all per-transaction adjustments are appended, the
        account's points_balance is recomputed by re-summing
        delta_points across the entire ledger."

        Claim: a T2 post that crosses STANDARD->GOLD produces (hop 1)
        spending_tier=GOLD; (hop 2) one EARN_ADJUST row sourced from T1
        with delta_points=+1250; (hop 3) points_balance equals the sum
        of all delta_points across the ledger.

        # difficulty: transitive_cascade/tier_upgrade_two_hop_backfill_cascade
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
        acc_after = re_get_account(acc["id"])
        # Hop 1.
        assert acc_after["spending_tier"] == "GOLD"
        # Hop 2.
        ledger = get_ledger(acc["id"])
        t1_adjusts = find_ledger_entries(
            ledger, entry_type="EARN_ADJUST", source_entity_id=t1["id"],
        )
        assert len(t1_adjusts) == 1
        assert t1_adjusts[0]["delta_points"] == 1_250
        # Hop 3 — balance equals signed sum of all ledger rows for the
        # account.
        ledger_sum = sum(
            e["delta_points"] for e in ledger
            if e.get("account_id") == acc["id"]
        )
        assert acc_after["points_balance"] == ledger_sum

    def test_tier_upgrade_recomputed_balance_matches_expected(self, api):
        """PRD §3.5: "After all per-transaction adjustments are
        appended, the account's points_balance is recomputed by
        re-summing delta_points across the entire ledger."

        Claim: the expected post-upgrade balance equals the signed sum
        of every ledger row on the account. After the tier-upgrade
        purchase the ledger contains five rows:
          * T1 EARN              +5,000   (100_000 * 500 / 10000)
          * T2 EARN             +25,000   (500_000 * 500 / 10000)
          * T1 EARN_ADJUST       +1,250   (backfill at GOLD: 6250-5000)
          * T2 EARN_ADJUST       +6,250   (backfill at GOLD: 31250-25000)
          * SIGNUP_BONUS        +60,000   (T2 crosses the 300,000-cent
                                           signup-window threshold of
                                           PRD §3.1 inside the 90-day
                                           window, so the bonus awards
                                           in the same posting)
        Total: 5000 + 25000 + 1250 + 6250 + 60000 = 97,500.

        # difficulty: transitive_cascade/tier_upgrade_two_hop_backfill_cascade
        """
        setup_clock_at(2026, 1, 1)
        ch, acc, cat = setup_account_with_fixed_bonus_category(
            base_rate_bps=500, year=2026, month=1, day=2,
        )
        advance_clock_to("2026-01-05T12:00:00.000Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=100_000,
        )
        advance_clock_to("2026-01-20T12:00:00.000Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=500_000,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == 97_500, (
            f"expected balance 97500 (T1 EARN 5000 + T2 EARN 25000 + "
            f"T1 EARN_ADJUST 1250 + T2 EARN_ADJUST 6250 + SIGNUP_BONUS "
            f"60000), got {acc_after['points_balance']}"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestValidationPriorityPairs:

    # ----- Instance: state_vs_fiscal_close_then_insufficient -----

    def test_closed_account_redemption_returns_account_closed_not_insufficient(
        self, api,
    ):
        """PRD §2.9: "Lifecycle-state precondition checks against the
        target Account (closed for write attempts, refund of an
        already-REVERSED source) come next and produce
        ERR_ACCOUNT_CLOSED or ERR_INVALID_STATE as the transition
        specifies. Only after all of the above have passed does the
        system evaluate the business rules — ... balance sufficiency
        ..."
        PRD §3.1: "After closure, every subsequent attempt to post a
        transaction, redeem a credit, transfer points, or activate a
        category against the same account is rejected with
        ERR_ACCOUNT_CLOSED."

        Claim: a Cardholder redemption against a CLOSED account
        (balance == 0 after FORFEIT) returns ERR_ACCOUNT_CLOSED rather
        than ERR_INSUFFICIENT_POINTS, even though both rules would
        independently fail.

        # difficulty: priority_pair_validation_conflict/state_vs_fiscal_close_then_insufficient
        """
        ch, closed = setup_closed_account(pre_close_spend_cents=20_000)
        assert closed["lifecycle_state"] == "CLOSED"
        assert closed["points_balance"] == 0
        # Request a large redemption — both balance and lifecycle
        # checks would fail, but state precedes fiscal in priority.
        resp = api.create_statement_credit(
            create_points_first_redemption_payload(
                account_id=closed["id"], requested_points=100_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED.value)

    def test_closed_account_transfer_returns_account_closed(self, api):
        """PRD §3.1: "After closure, every subsequent attempt to post
        a transaction, redeem a credit, transfer points, or activate a
        category against the same account is rejected with
        ERR_ACCOUNT_CLOSED."

        Claim: a Cardholder transfer against a CLOSED account that
        would also be insufficient returns ERR_ACCOUNT_CLOSED, not
        ERR_INSUFFICIENT_POINTS — state precedence over fiscal.

        # difficulty: priority_pair_validation_conflict/state_vs_fiscal_close_then_insufficient
        """
        ch, closed = setup_closed_account()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        resp = api.create_points_transfer(
            create_points_transfer_payload(
                account_id=closed["id"], partner_id=partner["id"],
                requested_partner_units=10_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED.value)

    # ----- Instance: referential_vs_constraint_refund_mismatch_and_partial -----

    def test_refund_mismatch_wins_over_partial_disallowed(self, api):
        """PRD §3.4: "Refunds carry an additional pair of checks: the
        referenced original must have txn_type equal to PURCHASE and
        must belong to the same account_id, otherwise
        ERR_REFUND_MISMATCH; the refund's amount_cents must equal the
        original's amount_cents (partial refunds are not supported),
        otherwise ERR_PARTIAL_REFUND_DISALLOWED".

        Claim: a REFUND on account A pointing at a PURCHASE on account
        B AND with a mismatched amount_cents resolves to
        ERR_REFUND_MISMATCH (referential check precedes constraint
        check per PRD §3.4 sequence and §2.9 priority).

        # difficulty: priority_pair_validation_conflict/referential_vs_constraint_refund_mismatch_and_partial
        """
        ch_a, acc_a, cat_a = setup_account_with_fixed_bonus_category(
            base_rate_bps=500,
        )
        ch_b, acc_b, _cat_b = setup_account_with_fixed_bonus_category()
        orig_on_b = post_purchase(
            cardholder_id=ch_b["id"], account_id=acc_b["id"],
            category_id=cat_a["id"], amount_cents=50_000,
        )
        # Refund from A with wrong amount AND wrong account.
        resp = api.create_transaction(
            create_refund_payload(
                account_id=acc_a["id"], category_id=cat_a["id"],
                amount_cents=12_345,
                original_transaction_id=orig_on_b["id"],
            ),
            make_cardholder_headers(ch_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_MISMATCH.value)

    def test_partial_refund_alone_returns_partial_disallowed(self, api):
        """PRD §3.4: "the refund's amount_cents must equal the
        original's amount_cents (partial refunds are not supported),
        otherwise ERR_PARTIAL_REFUND_DISALLOWED".

        Claim: when only the partial-amount constraint is violated
        (account_id matches and original is a PURCHASE on this
        account), the response is ERR_PARTIAL_REFUND_DISALLOWED — the
        single-failure isolation test that complements the priority
        test above.

        # difficulty: priority_pair_validation_conflict/referential_vs_constraint_refund_mismatch_and_partial
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=50_000,
        )
        resp = api.create_transaction(
            create_refund_payload(
                account_id=acc["id"], category_id=cat["id"],
                amount_cents=12_345,
                original_transaction_id=orig["id"],
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTIAL_REFUND_DISALLOWED.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecision:

    # ----- Instance: signup_bonus_exact_min_spend_boundary -----

    def test_signup_bonus_exact_300000_qualifies(self, api):
        """PRD §3.1: "When signup_bonus_state is PENDING and the
        qualifying total is at least three thousand dollars (three
        hundred thousand cents) — the comparison is at-or-greater-than,
        so exactly three thousand dollars triggers but two thousand
        nine hundred ninety-nine dollars and ninety-nine cents does not
        — the bonus is awarded immediately as described."

        Claim: a 300,000-cent PURCHASE qualifies and emits
        SIGNUP_BONUS(+60000).

        # difficulty: boundary_precision_check/signup_bonus_exact_min_spend_boundary
        """
        setup_clock_at(2026, 1, 1)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_state"] == "AWARDED"
        ledger = get_ledger(acc["id"])
        bonus_rows = find_ledger_entries(
            ledger, entry_type="SIGNUP_BONUS",
        )
        assert len(bonus_rows) == 1
        assert bonus_rows[0]["delta_points"] == 60_000

    def test_signup_bonus_299999_does_not_qualify(self, api):
        """PRD §3.1: "exactly three thousand dollars triggers but two
        thousand nine hundred ninety-nine dollars and ninety-nine cents
        does not".

        Claim: a 299,999-cent PURCHASE inside the window leaves
        signup_bonus_state == PENDING; no SIGNUP_BONUS row exists.

        # difficulty: boundary_precision_check/signup_bonus_exact_min_spend_boundary
        """
        setup_clock_at(2026, 1, 1)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS - 1,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_state"] == "PENDING"
        ledger = get_ledger(acc["id"])
        bonus_rows = find_ledger_entries(
            ledger, entry_type="SIGNUP_BONUS",
        )
        assert len(bonus_rows) == 0

    # ----- Instance: transfer_increment_zero_and_partial_multiple_boundary -----

    @pytest.mark.parametrize("units", [0, 1_500])
    def test_invalid_increment_rejected(self, api, units):
        """PRD §3.7: "verifies that requested_partner_units is strictly
        greater than zero and that the remainder of
        requested_partner_units divided by the partner's
        min_transfer_increment is zero — that is, the requested units
        must be a positive integer multiple of the partner's minimum
        increment (otherwise ERR_INVALID_TRANSFER_INCREMENT)".

        Claim: zero units AND 1500 units (with min_increment=1000) both
        return ERR_INVALID_TRANSFER_INCREMENT.

        # difficulty: boundary_precision_check/transfer_increment_zero_and_partial_multiple_boundary
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        resp = api.create_points_transfer(
            create_points_transfer_payload(
                account_id=acc["id"], partner_id=partner["id"],
                requested_partner_units=units,
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_TRANSFER_INCREMENT.value,
        )

    @pytest.mark.parametrize("units", [1_000, 2_000])
    def test_exact_increment_multiples_accepted(self, api, units):
        """PRD §3.7: "the requested units must be a positive integer
        multiple of the partner's minimum increment".

        Claim: 1000 and 2000 units (exact multiples of 1000) both
        succeed and produce points_debited = units * conversion_ratio.

        # difficulty: boundary_precision_check/transfer_increment_zero_and_partial_multiple_boundary
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=units,
        )
        assert transfer["points_debited"] == units * 10


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    # ----- Instance: points_transfer_blocked_by_account_lifecycle -----

    def test_confirm_on_auto_reversed_transfer_returns_invalid_state(
        self, api,
    ):
        """PRD §3.7: "A PlatformAdmin confirms the transfer by
        acknowledging on behalf of the simulated partner, requiring the
        account's lifecycle_state to be ACTIVE and the transfer's
        status to be PENDING".
        PRD §3.1: "A PlatformAdmin may also mark an ACTIVE account
        DELINQUENT. This transition reverses every PointsTransfer on
        the account whose status is PENDING (cascade hop one)".

        Claim: a PENDING transfer that gets auto-reversed by the
        DELINQUENT cascade cannot be confirmed afterwards — confirm
        returns ERR_INVALID_STATE because the transfer's status is no
        longer PENDING.

        # difficulty: cross_entity_state_dependency/points_transfer_blocked_by_account_lifecycle
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        mark_account_delinquent(acc["id"])
        # Transfer is auto-reversed by the cascade.
        resp = api.confirm_points_transfer(
            transfer["id"], None,
            __import__("test_helpers").TEST_USERS["admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_new_transfer_on_delinquent_account_blocked(self, api):
        """PRD §2.9: "Lifecycle-state precondition checks against the
        target Account (closed for write attempts, refund of an
        already-REVERSED source) come next and produce
        ERR_ACCOUNT_CLOSED or ERR_INVALID_STATE as the transition
        specifies."

        NOTE: PRD §3.1 enumerates the lifecycle-blocking errors for the
        DELINQUENT-write case only for the CLOSED case (which yields
        ERR_ACCOUNT_CLOSED) and the earn-side effect ("every purchase
        post earns zero points"). The PRD does not name an error_id
        for "new transfer initiation on DELINQUENT account"; in
        practice both ERR_INVALID_STATE and ERR_ACCOUNT_CLOSED are
        plausible reads. This test therefore asserts only that the
        request is rejected (not 2xx), without pinning the error_id.

        Claim: a new transfer initiation on a DELINQUENT account does
        NOT succeed (PRD §3.1 forbids ongoing earn/transfer/redeem
        during DELINQUENT).

        # difficulty: cross_entity_state_dependency/points_transfer_blocked_by_account_lifecycle
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        mark_account_delinquent(acc["id"])
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        resp = api.create_points_transfer(
            create_points_transfer_payload(
                account_id=acc["id"], partner_id=partner["id"],
                requested_partner_units=1_000,
            ),
            make_cardholder_headers(ch["id"]),
        )
        # Reject (4xx) — exact error_id is not uniquely pinned by PRD
        # for the DELINQUENT-write case, so we accept the two plausible
        # options.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_ACCOUNT_CLOSED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )

    # ----- Instance: quarterly_activation_blocked_by_category_type -----

    def test_activate_baseline_category_rejected(self, api):
        """PRD §3.2: "the referenced category has category_type equal
        to ROTATING_QUARTERLY (otherwise ERR_CATEGORY_NOT_ACTIVATABLE)".

        Claim: activating a BASELINE category returns
        ERR_CATEGORY_NOT_ACTIVATABLE.

        # difficulty: cross_entity_state_dependency/quarterly_activation_blocked_by_category_type
        """
        ch, acc = create_cardholder_and_account()
        advance_clock_to("2026-04-15T12:00:00.000Z")
        baseline = register_baseline_category(base_rate_bps=100)
        resp = api.activate_category(
            acc["id"],
            create_activation_payload(
                category_id=baseline["id"], quarter_label="2026Q2",
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_CATEGORY_NOT_ACTIVATABLE.value,
        )

    def test_activate_fixed_bonus_category_rejected(self, api):
        """PRD §3.2: "the referenced category has category_type equal
        to ROTATING_QUARTERLY (otherwise ERR_CATEGORY_NOT_ACTIVATABLE)".

        Claim: activating a FIXED_BONUS category returns
        ERR_CATEGORY_NOT_ACTIVATABLE — a different entity pair than the
        PointsTransfer/Account lifecycle case.

        # difficulty: cross_entity_state_dependency/quarterly_activation_blocked_by_category_type
        """
        ch, acc, fixed_cat = setup_account_with_fixed_bonus_category()
        advance_clock_to("2026-04-15T12:00:00.000Z")
        resp = api.activate_category(
            acc["id"],
            create_activation_payload(
                category_id=fixed_cat["id"], quarter_label="2026Q2",
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_CATEGORY_NOT_ACTIVATABLE.value,
        )


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    # ----- Instance: signup_window_half_open_at_deadline -----

    def test_signup_purchase_at_exact_deadline_excluded(self, api):
        """PRD §2.12: "The signup window of an Account is the half-open
        interval beginning at opened_at (inclusive) and ending at
        signup_bonus_deadline_at (exclusive), where
        signup_bonus_deadline_at is precisely 90 days after opened_at."
        PRD §3.1: "whose posted_at is at or after opened_at and
        strictly before signup_bonus_deadline_at".

        Claim: a PURCHASE posted at exactly signup_bonus_deadline_at
        (the exclusive upper bound) does NOT count; qualifying spend
        remains 0.

        # difficulty: resource_temporal_overlap/signup_window_half_open_at_deadline
        """
        setup_clock_at(2026, 1, 1)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        # 2026-01-01 + 90 days = 2026-04-01T00:00:00Z.
        advance_clock_to("2026-04-01T00:00:00.000Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_qualifying_spend_cents"] == 0

    def test_signup_purchase_one_ms_before_deadline_qualifies(self, api):
        """PRD §3.1: "whose posted_at is at or after opened_at and
        strictly before signup_bonus_deadline_at".

        Claim: a PURCHASE posted one ms before
        signup_bonus_deadline_at counts and triggers AWARDED at the
        minimum threshold.

        # difficulty: resource_temporal_overlap/signup_window_half_open_at_deadline
        """
        setup_clock_at(2026, 1, 1)
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=500)
        advance_clock_to("2026-03-31T23:59:59.999Z")
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=SIGNUP_MIN_SPEND_CENTS,
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["signup_bonus_state"] == "AWARDED"

    # ----- Instance: quarterly_activation_uniqueness_per_quarter -----

    def test_two_quarters_can_coexist_for_same_account_category(self, api):
        """PRD §3.2: "no QuarterlyActivation already exists with the
        same account_id, category_id, and quarter_label (otherwise
        ERR_ACTIVATION_ALREADY_EXISTS)".

        Claim: two activations on (account, category) but different
        quarter_label (2026Q2 and 2026Q3) coexist — uniqueness is on
        the full triple.

        # difficulty: resource_temporal_overlap/quarterly_activation_uniqueness_per_quarter
        """
        ch, acc, cat = setup_account_with_rotating_category()
        # First activation Q2.
        advance_clock_to("2026-04-15T12:00:00.000Z")
        a1 = activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q2",
        )
        # Second activation Q3 — different quarter bucket, allowed.
        advance_clock_to("2026-06-18T12:00:00.000Z")
        a2 = activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q3",
        )
        assert a1["status"] == "ACTIVATED"
        assert a2["status"] == "ACTIVATED"
        assert a1["quarter_label"] != a2["quarter_label"]

    def test_same_quarter_duplicate_rejected(self, api):
        """PRD §3.2: "no QuarterlyActivation already exists with the
        same account_id, category_id, and quarter_label (otherwise
        ERR_ACTIVATION_ALREADY_EXISTS)".

        Claim: two activations with the SAME (account, category,
        quarter_label) triple — the second is rejected with
        ERR_ACTIVATION_ALREADY_EXISTS. Distinct interval semantics from
        the half-open signup window above (discrete quarter buckets).

        # difficulty: resource_temporal_overlap/quarterly_activation_uniqueness_per_quarter
        """
        ch, acc, cat = setup_account_with_rotating_category()
        advance_clock_to("2026-04-15T12:00:00.000Z")
        activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q2",
        )
        resp = api.activate_category(
            acc["id"],
            create_activation_payload(
                category_id=cat["id"], quarter_label="2026Q2",
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACTIVATION_ALREADY_EXISTS.value,
        )


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    # ----- Instance: refund_preserves_net_points_invariant -----

    def test_full_refund_net_points_invariant_holds(self, api):
        """PRD §3.4: "A REFUND post does not earn its own row of
        points; instead it flips the original Transaction.status to
        REVERSED, appends an EARN_ADJUST ledger entry whose
        delta_points is the negation of the original transaction's
        points_provisional".

        Claim: SUM(delta_points where source_entity_id in {T_purchase.id,
        T_refund.id}) over the ledger == 0. Net delta across the EARN
        and EARN_ADJUST pair attributable to T_purchase is zero.

        # difficulty: compensating_invariant/refund_preserves_net_points_invariant
        """
        # 100 bps category to keep the math simple.
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=100)
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=50_000,
        )
        # points_provisional = floor(50000 * 100 / 10000) = 500.
        assert orig["points_provisional"] == 500
        post_refund(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=50_000,
            original_transaction_id=orig["id"],
        )
        ledger = get_ledger(acc["id"])
        related = [
            e for e in ledger
            if e.get("source_entity_id") == orig["id"]
        ]
        net = sum(e["delta_points"] for e in related)
        assert net == 0, (
            f"EARN + EARN_ADJUST sourced from T_purchase must net to "
            f"zero; got {net}"
        )

    def test_refund_returns_balance_to_pre_purchase_baseline(self, api):
        """PRD §3.4: "A REFUND post ... appends an EARN_ADJUST ledger
        entry whose delta_points is the negation of the original
        transaction's points_provisional".
        PRD §2.7: "Every change to it is materialised by appending
        exactly one row to the PointsLedgerEntry ledger and then
        recomputing points_balance as the signed sum of delta_points
        over all entries for the account."

        Claim: after a full PURCHASE+REFUND pair, points_balance is
        unchanged from its pre-purchase value.

        # difficulty: compensating_invariant/refund_preserves_net_points_invariant
        """
        ch, acc = create_cardholder_and_account()
        cat = register_fixed_bonus_category(base_rate_bps=100)
        baseline = acc["points_balance"]
        orig = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=50_000,
        )
        post_refund(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=50_000,
            original_transaction_id=orig["id"],
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == baseline

    # ----- Instance: transfer_reverse_preserves_balance_invariant -----

    def test_transfer_reverse_preserves_balance(self, api):
        """PRD §3.7: "reversal appends a TRANSFER_REVERSE ledger entry
        whose delta_points is the positive points_debited, advances
        the transfer status to REVERSED, and recomputes the account's
        points_balance (the invariant is that the TRANSFER_DEBIT plus
        TRANSFER_REVERSE pair sums to a net delta of zero points)."

        Claim: after debit + reverse, points_balance returns to the
        pre-transfer value, and the (TRANSFER_DEBIT, TRANSFER_REVERSE)
        pair sums to zero.

        # difficulty: compensating_invariant/transfer_reverse_preserves_balance_invariant
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        before = acc["points_balance"]
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        from test_helpers import reverse_points_transfer
        reverse_points_transfer(
            transfer_id=transfer["id"], cardholder_id=ch["id"],
        )
        ledger = get_ledger(acc["id"])
        debit_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_DEBIT",
            source_entity_id=transfer["id"],
        )
        rev_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_REVERSE",
            source_entity_id=transfer["id"],
        )
        pair_sum = sum(
            e["delta_points"] for e in debit_rows + rev_rows
        )
        assert pair_sum == 0
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == before

    def test_transfer_debit_and_reverse_emit_signed_pair(self, api):
        """PRD §3.7: "appends a TRANSFER_DEBIT ledger entry whose
        delta_points is the negation of points_debited" + "reversal
        appends a TRANSFER_REVERSE ledger entry whose delta_points is
        the positive points_debited".

        Claim: the TRANSFER_DEBIT row carries delta_points ==
        -points_debited and the TRANSFER_REVERSE row carries
        delta_points == +points_debited.

        # difficulty: compensating_invariant/transfer_reverse_preserves_balance_invariant
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        partner = register_partner(
            conversion_ratio_points_per_unit=10,
            min_transfer_increment=1000,
        )
        transfer = initiate_points_transfer(
            cardholder_id=ch["id"], account_id=acc["id"],
            partner_id=partner["id"], requested_partner_units=1_000,
        )
        from test_helpers import reverse_points_transfer
        reverse_points_transfer(
            transfer_id=transfer["id"], cardholder_id=ch["id"],
        )
        ledger = get_ledger(acc["id"])
        debit_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_DEBIT",
            source_entity_id=transfer["id"],
        )
        rev_rows = find_ledger_entries(
            ledger, entry_type="TRANSFER_REVERSE",
            source_entity_id=transfer["id"],
        )
        assert len(debit_rows) == 1
        assert len(rev_rows) == 1
        assert debit_rows[0]["delta_points"] == -transfer["points_debited"]
        assert rev_rows[0]["delta_points"] == transfer["points_debited"]

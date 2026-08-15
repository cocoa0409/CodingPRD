"""Final settlement: provisional vs final rounding variants, sum-then-round
per group, the pinned evaluation order, and the close sweep."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    close_ordering_at_window_end,
    create_campaign,
    create_group,
    create_prize,
    create_product,
    create_seller,
    create_submitted_paid_order,
    drive_campaign_to_closed,
    drive_campaign_to_reconciled,
    get_group_ledger,
    get_success_data,
    reset_clock,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]


class TestProvisionalVsFinalRounding:
    def test_proceeds_split_provisional_vs_final_rounding_divergence(self, api):
        """PRD §2.6: "The two proceeds variants differ only in *when* the
        rounding happens: the provisional computation rounds each order line's
        share to whole cents before summing across the order, whereas the
        final settlement sums unrounded per-line shares across an entire
        student group and rounds exactly once per group."
        PRD §3.7: "the group's `final_proceeds_cents` is that sum rounded half
        up to whole cents, rounded exactly once per group."

        Design: Difficulty/dual_variant_calc/proceeds_split_provisional_vs_final_rounding_divergence
        """
        reset_clock()
        campaign = create_campaign()
        group = create_group(campaign["id"])
        product = create_product(campaign["id"], unit_price_cents=999,
                                 supplier_unit_cost_cents=500,
                                 profit_share_bps=3333)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        for i in (1, 2, 3):
            create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_reconciled(campaign["id"], product["id"], 12,
                                     unit_cost_actual_cents=500)

        before_close = get_success_data(api.get_group(group["id"], TREAS))
        # Provisional: 3 x round_half_up(499 * 3333/10000) == 3 x 166 == 498.
        assert before_close["provisional_proceeds_cents"] == 498

        get_success_data(api.close_campaign(campaign["id"], TREAS))
        after_close = get_success_data(api.get_group(group["id"], TREAS))
        # Final: round_half_up(1497 * 3333/10000) == round_half_up(498.95) == 499.
        assert after_close["final_proceeds_cents"] == 499
        assert after_close["proceeds_balance_cents"] == 499, (
            "498 + 1 true-up credit")

        campaign_view = get_success_data(api.get_campaign(campaign["id"], TREAS))
        assert campaign_view["status"] == "CLOSED"
        # total net 3*(999-500) == 1497; general fund = 1497 - 499 - 0.
        assert campaign_view["general_fund_cents"] == 998

    def test_proceeds_divergence_true_up_credit_entry(self, api):
        """PRD §3.7: "the difference between the group's freshly computed
        final share and its `provisional_proceeds_cents` — the sum of the
        group's `PROVISIONAL_CREDIT` entries minus its `SALE_REVERSAL_DEBIT`
        entries — is posted as a `FINAL_TRUE_UP_CREDIT` when positive or a
        `FINAL_TRUE_UP_DEBIT` carrying the signed (negative) difference when
        negative, and skipped entirely when zero".

        Design: Difficulty/dual_variant_calc/proceeds_split_provisional_vs_final_rounding_divergence
        """
        reset_clock()
        campaign = create_campaign()
        group = create_group(campaign["id"])
        product = create_product(campaign["id"], unit_price_cents=999,
                                 supplier_unit_cost_cents=500,
                                 profit_share_bps=3333)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        for i in (1, 2, 3):
            create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_closed(campaign["id"], product["id"], 12,
                                 unit_cost_actual_cents=500)
        ledger = get_group_ledger(group["id"])
        true_ups = [e for e in ledger
                    if e["entry_type"] in ("FINAL_TRUE_UP_CREDIT",
                                           "FINAL_TRUE_UP_DEBIT")]
        assert len(true_ups) == 1
        assert true_ups[0]["entry_type"] == "FINAL_TRUE_UP_CREDIT"
        assert true_ups[0]["amount_cents"] == 1, (
            "499 final - 498 provisional = +1 true-up credit")


class TestSumThenRound:
    def test_group_share_sum_then_round_beats_per_line_sum(self, api):
        """PRD §2.6: "The two proceeds variants differ only in *when* the
        rounding happens: the provisional computation rounds each order line's
        share to whole cents before summing across the order, whereas the
        final settlement sums unrounded per-line shares across an entire
        student group and rounds exactly once per group."
        PRD §3.7: "is posted as a `FINAL_TRUE_UP_CREDIT` when positive or a
        `FINAL_TRUE_UP_DEBIT` carrying the signed (negative) difference when
        negative".

        Design: Difficulty/combinatorial_formula/group_share_sum_then_round_beats_per_line_sum
        """
        reset_clock()
        campaign = create_campaign()
        group = create_group(campaign["id"])
        product = create_product(campaign["id"], unit_price_cents=899,
                                 supplier_unit_cost_cents=600)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_submitted_paid_order(seller["id"], product["id"], 1)
        create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_closed(campaign["id"], product["id"], 12)

        group_view = get_success_data(api.get_group(group["id"], TREAS))
        # Provisional per line: round_half_up(299 * 5000/10000)
        # == round_half_up(149.5) == 150, twice -> 300.
        assert group_view["provisional_proceeds_cents"] == 300
        # Final: round_half_up(598 * 5000/10000) == round_half_up(299.0) == 299.
        assert group_view["final_proceeds_cents"] == 299
        assert group_view["proceeds_balance_cents"] == 299

        ledger = get_group_ledger(group["id"])
        true_ups = [e for e in ledger
                    if e["entry_type"] in ("FINAL_TRUE_UP_CREDIT",
                                           "FINAL_TRUE_UP_DEBIT")]
        assert len(true_ups) == 1
        assert true_ups[0]["entry_type"] == "FINAL_TRUE_UP_DEBIT"
        assert true_ups[0]["amount_cents"] == -1, (
            "299 final - 300 provisional = -1 true-up debit (signed)")

    def test_group_share_general_fund_absorbs_remainder(self, api):
        """PRD §3.7: "`general_fund_cents` is that total net minus the sum of
        all groups' final proceeds minus the campaign's
        `family_credits_cents` — the general fund deliberately absorbs the
        per-group rounding remainder."

        Design: Difficulty/combinatorial_formula/group_share_sum_then_round_beats_per_line_sum
        """
        reset_clock()
        campaign = create_campaign()
        group = create_group(campaign["id"])
        product = create_product(campaign["id"], unit_price_cents=899,
                                 supplier_unit_cost_cents=600)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_submitted_paid_order(seller["id"], product["id"], 1)
        create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_closed(campaign["id"], product["id"], 12)
        campaign_view = get_success_data(api.get_campaign(campaign["id"], TREAS))
        # total net 2*(899-600) == 598; general fund = 598 - 299 - 0 == 299.
        assert campaign_view["general_fund_cents"] == 299


class TestPinnedEvaluationOrder:
    def test_final_settlement_pinned_evaluation_order(self, api):
        """PRD §3.7: "Closing the books is the `Treasurer`'s act, moving the
        campaign `RECONCILED` → `CLOSED` and running the final settlement in a
        pinned evaluation order that breaks the apparent cycle between
        metrics, prizes, and shares. First, seller metrics are already final —
        the reconcile gate guarantees no open claims or returns and an expired
        return window. Second, the prize sweep has already been applied and
        prize chargebacks stand as posted."

        Design: Difficulty/combinatorial_formula/final_settlement_pinned_evaluation_order
        """
        reset_clock()
        campaign = create_campaign()
        group = create_group(campaign["id"])
        product = create_product(campaign["id"], unit_price_cents=1000,
                                 supplier_unit_cost_cents=600,
                                 profit_share_bps=3333)
        create_prize(campaign["id"], name="iPad", tier_type="REVENUE_CENTS",
                     threshold_value=2000, prize_cost_cents=300,
                     stock_quantity=1)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_submitted_paid_order(seller["id"], product["id"], 1)
        create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_closed(campaign["id"], product["id"], 12,
                                 unit_cost_actual_cents=600)

        ledger = get_group_ledger(group["id"])
        prize_debit = next(e for e in ledger
                           if e["entry_type"] == "PRIZE_COST_DEBIT")
        true_up = next(e for e in ledger
                       if e["entry_type"] in ("FINAL_TRUE_UP_CREDIT",
                                              "FINAL_TRUE_UP_DEBIT"))
        assert prize_debit["amount_cents"] == -300
        assert prize_debit["seq"] < true_up["seq"], (
            "the prize chargeback is posted before the close-time true-up — "
            "the pinned order is observable in the ledger replay sequence")

        group_view = get_success_data(api.get_group(group["id"], TREAS))
        # Provisional: 2 x round_half_up(400 * 3333/10000) == 2 x 133 == 266.
        assert group_view["provisional_proceeds_cents"] == 266
        # Final: round_half_up(800 * 3333/10000) == round_half_up(266.64) == 267.
        assert group_view["final_proceeds_cents"] == 267
        # Balance: 266 provisional + 1 true-up - 300 prize cost == -33.
        assert group_view["proceeds_balance_cents"] == -33

    def test_final_settlement_general_fund_with_prize_chargeback(self, api):
        """PRD §3.7: "Sixth, the PTO remainder: the campaign's total net is
        the sum over the same line set of effective quantity times the
        difference between price and actual cost, and `general_fund_cents` is
        that total net minus the sum of all groups' final proceeds minus the
        campaign's `family_credits_cents`".

        Design: Difficulty/combinatorial_formula/final_settlement_pinned_evaluation_order
        """
        reset_clock()
        campaign = create_campaign()
        group = create_group(campaign["id"])
        product = create_product(campaign["id"], unit_price_cents=1000,
                                 supplier_unit_cost_cents=600,
                                 profit_share_bps=3333)
        create_prize(campaign["id"], name="iPad", tier_type="REVENUE_CENTS",
                     threshold_value=2000, prize_cost_cents=300,
                     stock_quantity=1)
        seller = create_seller(group["id"])
        get_success_data(api.open_campaign(campaign["id"], ADMIN))
        create_submitted_paid_order(seller["id"], product["id"], 1)
        create_submitted_paid_order(seller["id"], product["id"], 1)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_closed(campaign["id"], product["id"], 12,
                                 unit_cost_actual_cents=600)
        campaign_view = get_success_data(api.get_campaign(campaign["id"], TREAS))
        # total net 2*(1000-600) == 800; general fund = 800 - 267 - 0 == 533.
        assert campaign_view["general_fund_cents"] == 533
        assert campaign_view["status"] == "CLOSED"


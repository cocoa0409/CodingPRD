"""Commission ladder (provisional/final, tier boundaries), settlement waterfall, and earnout payments."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_broker_headers,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Design: Difficulty/dual_variant_calc/commission_provisional_at_accept_vs_final_at_close
# ---------------------------------------------------------------------------
class TestProvisionalVsFinalCommission:
    def test_provisional_commission_set_at_accept(self, api):
        """PRD §3.6: "The deal's `provisional_commission_cents` is computed at this moment as the
        brokerage commission on the `accepted_price_cents` (the commission ladder is defined in
        Section 3.8)."

        Design: Difficulty/dual_variant_calc/commission_provisional_at_accept_vs_final_at_close
        """
        s = fx.setup_deal_under_loi(api, offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000)
        deal = fx.get_deal(api, s)
        assert deal["provisional_commission_cents"] == 5_600_000

    def test_final_commission_at_close_differs_from_provisional(self, api):
        """PRD §3.8: "The deal's `final_commission_cents` is computed as the brokerage commission on
        the escrow's `closing_price_cents`; this can differ from the provisional commission
        whenever the closing price re-traded away from the accepted price."

        Design: Difficulty/dual_variant_calc/commission_provisional_at_accept_vs_final_at_close
        """
        s = fx.setup_closed_deal(
            api, offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000,
            closing_price_cents=110_000_000, required_deposit_cents=5_000_000, deposit_amount_cents=5_000_000,
        )
        deal = s["deal"]
        assert deal["provisional_commission_cents"] == 5_600_000
        assert deal["final_commission_cents"] == 5_400_000
        assert deal["final_commission_cents"] != deal["provisional_commission_cents"]


# ---------------------------------------------------------------------------
# Design: Difficulty/combinatorial_formula/commission_lehman_marginal_ladder
# ---------------------------------------------------------------------------
class TestLehmanMarginalLadder:
    def test_commission_spans_three_marginal_tranches(self, api):
        """PRD §3.8: "The first one-million-dollar slice of the base is charged at five percent, the
        second at four percent, the third at three percent, and the fourth at two percent; any
        portion of the base beyond four million dollars is charged at a flat one percent."

        Design: Difficulty/combinatorial_formula/commission_lehman_marginal_ladder
        """
        s = fx.setup_deal_under_loi(
            api, offer_price_cents=250_000_000, earnest_deposit_cents=10_000_000,
            buyer_proof_of_funds_cents=40_000_000, buyer_net_worth_cents=200_000_000,
            asking_price_cents=250_000_000,
        )
        deal = fx.get_deal(api, s)
        # 100M@5% + 100M@4% + 50M@3% = 5_000_000 + 4_000_000 + 1_500_000
        assert deal["provisional_commission_cents"] == 10_500_000

    def test_commission_reaches_flat_one_percent_tier(self, api):
        """PRD §3.8: "Each slice's charge is the applicable rate applied only to the amount of the
        base that falls within that slice, and the charges are summed across the slices."

        Design: Difficulty/combinatorial_formula/commission_lehman_marginal_ladder
        """
        s = fx.setup_deal_under_loi(
            api, offer_price_cents=450_000_000, earnest_deposit_cents=10_000_000,
            buyer_proof_of_funds_cents=45_000_000, buyer_net_worth_cents=225_000_000,
            asking_price_cents=450_000_000,
        )
        deal = fx.get_deal(api, s)
        # 100M@5% + 100M@4% + 100M@3% + 100M@2% + 50M@1% = 14_000_000 + 500_000
        assert deal["provisional_commission_cents"] == 14_500_000


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/commission_tier_width_exact_boundary
# ---------------------------------------------------------------------------
class TestCommissionTierBoundary:
    def test_base_exactly_one_tier_width(self, api):
        """PRD §3.8: "A base of exactly one million dollars therefore consumes only the first tier."

        Design: Difficulty/boundary_precision_check/commission_tier_width_exact_boundary
        """
        s = fx.setup_deal_under_loi(
            api, offer_price_cents=100_000_000, earnest_deposit_cents=5_000_000,
            buyer_proof_of_funds_cents=20_000_000, asking_price_cents=100_000_000,
        )
        deal = fx.get_deal(api, s)
        assert deal["provisional_commission_cents"] == 5_000_000

    def test_base_one_cent_over_tier_width_spills_into_second_tier(self, api):
        """PRD §3.8: "The first one-million-dollar slice of the base is charged at five percent, the
        second at four percent, the third at three percent, and the fourth at two percent; any
        portion of the base beyond four million dollars is charged at a flat one percent."

        Design: Difficulty/boundary_precision_check/commission_tier_width_exact_boundary
        """
        s = fx.setup_deal_under_loi(
            api, offer_price_cents=100_000_100, earnest_deposit_cents=5_000_000,
            buyer_proof_of_funds_cents=20_000_000, asking_price_cents=100_000_000,
        )
        deal = fx.get_deal(api, s)
        # 100M@5% + 100@4% = 5_000_000 + 4
        assert deal["provisional_commission_cents"] == 5_000_004


# ---------------------------------------------------------------------------
# Design: Difficulty/combinatorial_formula/earnout_round_per_period_then_sum
# ---------------------------------------------------------------------------
class TestEarnoutPeriodRounding:
    def test_single_period_rounds_half_up(self, api):
        """PRD §3.9: "The period's payment is the deal's `earnout_total_cents` multiplied by that
        clamped performance ratio, divided by the deal's `earnout_periods`, and rounded half up
        to whole cents. That already-rounded per-period payment is then added to the deal's
        accumulated `earnout_paid_cents`."

        Design: Difficulty/combinatorial_formula/earnout_round_per_period_then_sum
        """
        s = fx.setup_closed_deal(
            api, offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000,
            earnout_amount_cents=10_000_000, earnout_periods=3,
            closing_price_cents=110_000_000, required_deposit_cents=5_000_000, deposit_amount_cents=5_000_000,
        )
        broker_hdr = make_broker_headers(s["broker"]["id"])
        data = validate_success(
            api.record_earnout_period(s["deal"]["id"], {"actual_sde_cents": 40_000_000}, broker_hdr)
        )
        # round_half_up(10_000_000 * 1.0 / 3) == 3_333_333
        assert data["earnout_paid_cents"] == 3_333_333

    def test_two_periods_accumulate_rounded_figures(self, api):
        """PRD §3.9: "The rounding is applied to each period's payment before it is accumulated —
        the running total is a sum of rounded per-period figures, never a single rounding of an
        aggregate."

        Design: Difficulty/combinatorial_formula/earnout_round_per_period_then_sum
        """
        s = fx.setup_closed_deal(
            api, offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000,
            earnout_amount_cents=10_000_000, earnout_periods=3,
            closing_price_cents=110_000_000, required_deposit_cents=5_000_000, deposit_amount_cents=5_000_000,
        )
        broker_hdr = make_broker_headers(s["broker"]["id"])
        validate_success(api.record_earnout_period(s["deal"]["id"], {"actual_sde_cents": 40_000_000}, broker_hdr))
        data = validate_success(
            api.record_earnout_period(s["deal"]["id"], {"actual_sde_cents": 40_000_000}, broker_hdr)
        )
        # 3_333_333 + 3_333_333 == 6_666_666 (NOT round(20_000_000/3) == 6_666_667)
        assert data["earnout_paid_cents"] == 6_666_666


def test_close_escrow_not_funded_rejected(api):
    """PRD §3.8: "Closing is performed by an `EscrowAgent` against a `FUNDED` account; a close
    attempted on an account that is not `FUNDED` is rejected with `ERR_ESCROW_NOT_FUNDED`."

    Design: Corner/state_machines/escrow_close_not_funded_returns_error
    """
    s = fx.setup_deal_in_escrow(api)  # escrow OPENED, no deposit
    resp = api.close_escrow(s["escrow"]["id"], TEST_USERS["escrow_agent_headers"])
    validate_error(resp, ApiErrorId.ERR_ESCROW_NOT_FUNDED.value)


def test_seller_net_proceeds_and_broker_ledger_on_close(api):
    """PRD §3.8: "The seller's net proceeds are then the closing price minus the final commission,
    minus the rounded escrow fee, minus the earnout holdback."
    PRD §3.8: "The broker's `accrued_commission_cents` is increased by the `final_commission_cents`."

    Design: Corner/calculations/seller_net_proceeds_and_broker_ledger_on_close
    """
    s = fx.setup_closed_deal(
        api, offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000,
        earnout_amount_cents=30_000_000, earnout_periods=3,
        closing_price_cents=110_000_000, required_deposit_cents=5_000_000, deposit_amount_cents=5_000_000,
    )
    # 110_000_000 - 5_400_000 (final commission) - 1_100_000 (1% fee) - 30_000_000 (earnout) = 73_500_000
    assert s["deal"]["seller_net_proceeds_cents"] == 73_500_000
    assert s["broker"]["accrued_commission_cents"] == 5_400_000
    assert s["deal"]["status"] == "CLOSED"
    listing = fx.get_listing(api, s["broker"]["id"], s["listing"]["id"])
    assert listing["status"] == "SOLD"

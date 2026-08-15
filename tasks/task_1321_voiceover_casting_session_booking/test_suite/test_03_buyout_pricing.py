"""Buyout pricing: provisional quote vs final buyout, per-line rounding, and
the agency commission tier waterfall."""
from test_helpers import (
    assert_project,
    create_cast_project,
    create_casting_project,
    create_client,
    create_project,
    create_talent,
    get_usage_terms,
    open_casting,
    select_talent,
    validate_success,
)
from test_helpers.fixtures import CD, get_project
from test_helpers.test_users import make_client_headers


class TestBuyoutQuoteCalculation:
    def test_buyout_quote_broadcast_spots_uplift(self, api):
        """PRD §3.2: "The quote assumes union scale: a base of 65000 cents is
        multiplied by a usage multiplier — 2.50 for `BROADCAST`, 1.50 for
        `DIGITAL`, or, for `TERM`, 1.00 plus 0.10 for each month of
        `term_months` — and then by a spot multiplier of 1.00 plus 0.20 for
        every spot beyond the first (a single-spot project therefore carries
        no uplift)."

        Design: Corner/calculations/buyout_quote_broadcast_spots_uplift
        """
        client = create_client()
        project = create_project(client, usage_type="BROADCAST", spots_count=3)
        resp = api.open_casting(project["id"], CD)
        data = validate_success(resp, expected_status=200)
        # 65000 * 2.50 * (1.00 + 0.20 * 2) = 227500
        assert data["buyout_quote_cents"] == 227500

    def test_buyout_quote_term_uses_term_months(self, api):
        """PRD §3.2: "or, for `TERM`, 1.00 plus 0.10 for each month of
        `term_months`".

        Design: Corner/calculations/buyout_quote_term_uses_term_months
        """
        client = create_client()
        project = create_project(client, usage_type="TERM", term_months=6,
                                 spots_count=1)
        resp = api.open_casting(project["id"], CD)
        data = validate_success(resp, expected_status=200)
        # 65000 * (1.00 + 0.10 * 6) * 1.00 = 104000
        assert data["buyout_quote_cents"] == 104000


class TestBuyoutQuoteVsFinal:
    def test_quote_uses_union_scale_regardless_of_actual_talent(self, api):
        """PRD §3.2: "Because the quote assumes union scale rather than any
        particular artist's fee, it routinely differs from the final figure
        computed at cast time."

        Design: Difficulty/dual_variant_calc/buyout_quote_vs_final_on_project
        """
        client = create_client()
        talent = create_talent(union_status="NON_UNION", base_session_fee_cents=60000)
        project = create_project(client, usage_type="BROADCAST", spots_count=2)
        open_casting(project["id"])
        data = get_project(project["id"])
        # Quote: 65000 * 2.50 * 1.20 = 195000 (union-scale base, talent unknown).
        assert data["buyout_quote_cents"] == 195000

    def test_final_buyout_differs_from_quote_for_non_union_talent(self, api):
        """PRD §3.4: "line one is the talent's `base_session_fee_cents`
        multiplied by the same usage multiplier used for the quote ... and by a
        union multiplier that is 1.00 for `UNION`, 1.00 for `FICORE`, and 0.85
        for `NON_UNION`; line two is the incremental spot uplift, computed as
        line one multiplied by the spot multiplier minus 1.00".

        Design: Difficulty/dual_variant_calc/buyout_quote_vs_final_on_project
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="NON_UNION",
                                 base_session_fee_cents=60000),
            usage_type="BROADCAST", spots_count=2,
        )
        project = ctx["project"]
        # line1 = 60000 * 2.50 * 0.85 = 127500; line2 = 127500 * 0.20 = 25500.
        assert project["buyout_quote_cents"] == 195000
        assert project["buyout_final_cents"] == 153000
        assert project["buyout_quote_cents"] != project["buyout_final_cents"]


class TestBuyoutFinalPerLineItemRounding:
    def test_per_line_item_rounding_then_sum(self, api):
        """PRD §3.4: "Each line item is individually rounded half-up to integer
        cents, and the total is the sum of the two rounded line items."
        PRD §2.6: "The final buyout computation applies this rounding per line
        item and then sums the rounded line items — the per-line-then-sum order
        is part of the contract and is described fully in Section 3.4."

        Design: Difficulty/combinatorial_formula/buyout_final_per_line_item_rounding
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="NON_UNION",
                                 base_session_fee_cents=33333),
            usage_type="TERM", term_months=7, spots_count=3,
        )
        # line1 = 33333 * 1.70 * 0.85 = 48166.0185 -> 48166
        # line2 = 48166.0185 * 0.40 = 19266.4074 -> 19266
        # total = 48166 + 19266 = 67432 (sum-then-round would give 67431)
        assert ctx["project"]["buyout_final_cents"] == 67432

    def test_usage_terms_mirror_final_buyout_and_split(self, api):
        """PRD §3.4: "The row mirrors the project's `usage_type` and
        `term_months` (null for non-`TERM` projects), stores the computed
        `buyout_cents` equal to the final buyout, and splits that amount into
        the agency's `agent_commission_cents` and the artist's
        `talent_payout_cents`."

        Design: Difficulty/combinatorial_formula/buyout_final_per_line_item_rounding
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="NON_UNION",
                                 base_session_fee_cents=33333),
            usage_type="TERM", term_months=7, spots_count=3,
        )
        terms = get_usage_terms(ctx["project"]["id"])
        assert terms["buyout_cents"] == 67432
        # 67432 < 500000 -> tier 10%, NON_UNION keeps full rate.
        # commission = round_half_up(67432 * 0.10) = 6743; payout = 60689.
        assert terms["agent_commission_cents"] == 6743
        assert terms["talent_payout_cents"] == 60689


class TestAgentCommissionTieredWaterfall:
    def test_tier2_boundary_buyout_union_commission(self, api):
        """PRD §3.4: "The commission follows a volume-tier waterfall: under
        500000 cents the agency takes 10 percent; from 500000 cents up to but
        not including 1500000 cents it takes 15 percent; at 1500000 cents and
        above it takes 20 percent. A `UNION` artist receives a
        two-percentage-point reduction on the applicable tier rate, subject to
        a floor of 5 percent."

        Design: Difficulty/combinatorial_formula/agent_commission_tiered_waterfall
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="UNION", base_session_fee_cents=200000),
            usage_type="BROADCAST", spots_count=1,
        )
        # buyout_final = 200000 * 2.50 * 1.00 = 500000 -> tier 2 (15%);
        # UNION reduction -> 13%; commission = 65000; payout = 435000.
        assert ctx["project"]["buyout_final_cents"] == 500000
        terms = get_usage_terms(ctx["project"]["id"])
        assert terms["agent_commission_cents"] == 65000
        assert terms["talent_payout_cents"] == 435000

    def test_commission_plus_payout_equals_buyout(self, api):
        """PRD §3.4: "The commission amount itself is rounded half-up to
        integer cents, and the payout is the buyout minus the commission."

        Design: Difficulty/combinatorial_formula/agent_commission_tiered_waterfall
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="UNION", base_session_fee_cents=200000),
            usage_type="BROADCAST", spots_count=1,
        )
        terms = get_usage_terms(ctx["project"]["id"])
        assert terms["buyout_cents"] == 500000
        assert (terms["agent_commission_cents"] + terms["talent_payout_cents"]
                == terms["buyout_cents"])


class TestCommissionTierBoundary:
    def test_buyout_exactly_500k_falls_in_tier2(self, api):
        """PRD §3.4: "from 500000 cents up to but not including 1500000 cents
        it takes 15 percent".

        Design: Difficulty/boundary_precision_check/commission_tier_at_exactly_500k_boundary
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="UNION", base_session_fee_cents=200000),
            usage_type="BROADCAST", spots_count=1,
        )
        assert ctx["project"]["buyout_final_cents"] == 500000
        terms = get_usage_terms(ctx["project"]["id"])
        # 500000 is inside [500000, 1500000): 15% tier, UNION -> 13% -> 65000.
        assert terms["agent_commission_cents"] == 65000
        assert terms["talent_payout_cents"] == 435000

    def test_buyout_just_below_500k_stays_in_tier1(self, api):
        """PRD §3.4: "under 500000 cents the agency takes 10 percent".

        Design: Difficulty/boundary_precision_check/commission_tier_at_exactly_500k_boundary
        """
        ctx = create_cast_project(
            talent=create_talent(union_status="NON_UNION",
                                 base_session_fee_cents=199999),
            usage_type="BROADCAST", spots_count=1,
        )
        # line1 = 199999 * 2.50 * 0.85 = 424997.875 -> 424998; single spot.
        assert ctx["project"]["buyout_final_cents"] == 424998
        terms = get_usage_terms(ctx["project"]["id"])
        # 424998 < 500000 -> 10%; commission = round(424998 * 0.10) = 42500.
        assert terms["agent_commission_cents"] == 42500
        assert terms["talent_payout_cents"] == 424998 - 42500

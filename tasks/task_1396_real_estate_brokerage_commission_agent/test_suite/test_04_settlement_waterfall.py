"""Settlement waterfall calculations, caps, rounding order, accumulator order (PRD §3.6, §2.6)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_deal_payload,
    setup_active_agent, setup_active_plan_p1, setup_agent_on_plan,
    setup_agent_with_debit, create_draft_deal, setup_closed_deal, setup_settled_deal,
    get_settlement_legs, get_leg_by_type, get_window_for_agent,
    make_transaction_coordinator_headers,
)


class TestDualVariantEstimateVsFinal:
    def test_provisional_estimate_vs_final_settlement_on_debit_shift(self, api):
        """PRD §3.6: "Because intervening settlements move the accumulators and
        the debit balance, the provisional estimate and the later final
        settlement legitimately differ for identical deal data."
        PRD §3.6 step 9: "debit_recovery_cents is the lesser of the agent share
        remaining after the fees and the agent's debit_balance_cents read before
        this deal posts".

        Design: Difficulty/dual_variant_calc/provisional_estimate_vs_final_settlement_on_debit_shift
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Alice Agent")
        deal = setup_closed_deal(agent["id"], address="1 Main St",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        est = get_success_data(api.payout_estimate(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert est["debit_recovery_cents"] == 0
        assert est["agent_net_cents"] == 627000
        get_success_data(api.create_debit_adjustment(
            agent["id"], {"amount_cents": 150000, "reason": "advance E&O premium"},
            TEST_USERS["broker_admin_headers"]))
        settlement = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert settlement["debit_recovery_cents"] == 150000
        assert settlement["agent_net_cents"] == 477000
        assert settlement["company_dollar_cents"] == 282000

    def test_debit_recovery_zeroes_agent_balance_after_settle(self, api):
        """PRD §3.6 step 9: "`debit_recovery_cents` is the lesser of the agent
        share remaining after the fees and the agent's `debit_balance_cents`
        read before this deal posts; it is swept to the company." PRD §2.11:
        "An agent's `debit_balance_cents` always equals the sum of `amount_cents`
        over all of the agent's ledger entries".

        Design: Difficulty/dual_variant_calc/provisional_estimate_vs_final_settlement_on_debit_shift
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Alice Agent")
        deal = setup_closed_deal(agent["id"], gross_commission_cents=1000000, closing_date="2026-01-15")
        get_success_data(api.create_debit_adjustment(
            agent["id"], {"amount_cents": 150000, "reason": "advance E&O premium"},
            TEST_USERS["broker_admin_headers"]))
        api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        after = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert after["debit_balance_cents"] == 0


class TestCombinatorialFormula:
    def test_waterfall_tier_branch_with_debit_recovery(self, api):
        """PRD §3.6 step 3: "royalty_cents is the lesser of the tentative royalty
        and the cap room"; step 4: "The applicable tier is the first tier, in
        ascending threshold order, whose threshold_company_dollar_cents strictly
        exceeds the window's pre-deal company_dollar_accrued_cents"; step 9:
        "debit_recovery_cents is the lesser of the agent share remaining after
        the fees and the agent's debit_balance_cents read before this deal
        posts".

        Design: Difficulty/combinatorial_formula/waterfall_tier_branch_with_nested_min_mode_a
        """
        agent, plan, _e = setup_agent_with_debit(150000, agent_name="Cara Combo")
        deal = setup_closed_deal(agent["id"], address="2 Nested Min Rd",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert s["royalty_cents"] == 60000
        assert s["tier_index_applied"] == 0
        assert s["company_dollar_cents"] == 282000
        assert s["cap_clipped"] is False
        assert s["agent_gross_cents"] == 658000
        assert s["eo_fee_cents"] == 6000
        assert s["transaction_fee_cents"] == 25000
        assert s["debit_recovery_cents"] == 150000
        assert s["agent_net_cents"] == 477000

    def test_unclipped_tier_zero_split_of_30_percent(self, api):
        """PRD §3.6 step 4: "A tentative company dollar is after_royalty_cents
        multiplied by that tier's broker_split_pct, rounded half up to whole
        cents. ... company_dollar_cents is the lesser of the tentative company
        dollar and the cap room" — at accrued 0 with threshold 2500000, no clip.

        Design: Difficulty/combinatorial_formula/waterfall_tier_branch_with_nested_min_mode_a
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Cara Combo")
        deal = setup_closed_deal(agent["id"], gross_commission_cents=1000000, closing_date="2026-01-15")
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        # 0.06*1000000=60000 royalty; after_royalty 940000; 30% => 282000
        assert s["royalty_cents"] == 60000
        assert s["after_royalty_cents"] == 940000
        assert s["company_dollar_cents"] == 282000
        assert s["cap_clipped"] is False
        assert s["agent_gross_cents"] == 658000


class TestPerStepRoundingOrder:
    def test_referral_rounds_before_royalty_consumes_it(self, api):
        """PRD §2.6: "every commission component is rounded half up to whole cents
        at its own waterfall step, before any later step consumes the value.
        Implementations must not carry fractional cents through the waterfall and
        round once at the end — per-step rounding followed by exact integer
        composition is the authoritative order."

        Design: Difficulty/combinatorial_formula/per_step_rounding_order_mode_b
        """
        ref = setup_active_agent(name="Rick Referrer")
        agent, plan, _e = setup_agent_on_plan(agent_name="Dana Deal")
        deal = setup_closed_deal(
            agent["id"], address="5 Rounding Way", gross_commission_cents=105555,
            closing_date="2026-01-15", referral_pct=0.25, referral_agent_id=ref["id"])
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        # 0.25 * 105555 = 26388.75 -> 26389 (rounded at the referral step)
        assert s["referral_fee_cents"] == 26389
        # royalty on the ALREADY-ROUNDED adjusted 79166: 0.06*79166 = 4749.96 -> 4750
        assert s["royalty_cents"] == 4750
        assert s["company_dollar_cents"] == 22325
        assert s["agent_net_cents"] == 21091

    def test_leg_conservation_on_rounded_settlement(self, api):
        """PRD §2.11: "The disbursement legs created by a settlement always sum,
        to the cent, to the deal's gross_commission_cents."

        Design: Difficulty/combinatorial_formula/per_step_rounding_order_mode_b
        """
        ref = setup_active_agent(name="Rick Referrer")
        agent, plan, _e = setup_agent_on_plan(agent_name="Dana Deal")
        deal = setup_closed_deal(
            agent["id"], gross_commission_cents=105555, closing_date="2026-01-15",
            referral_pct=0.25, referral_agent_id=ref["id"])
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        legs = get_settlement_legs(s["id"])
        assert sum(leg["amount_cents"] for leg in legs) == 105555


class TestSettlementOrderGovernsCapAllocation:
    def test_first_settled_consumes_cap_room_first(self, api):
        """PRD §3.6: "every previously posted, non-reversed settlement contributes
        to them regardless of its own closing date, so settlement-time order
        governs cap allocation — whichever deal settles first consumes cap room
        first."

        Design: Difficulty/combinatorial_formula/settlement_order_governs_cap_allocation_mode_c
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Oliver Order")
        big = setup_closed_deal(agent["id"], address="10 Big Blvd",
                                gross_commission_cents=3000000, closing_date="2026-01-10")
        small = setup_closed_deal(agent["id"], address="11 Small St",
                                  gross_commission_cents=1000000, closing_date="2026-01-20")
        # SMALL settles first despite the later closing date
        small_s = get_success_data(api.settle_deal(small["id"], TEST_USERS["transaction_coordinator_headers"]))
        big_s = get_success_data(api.settle_deal(big["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert small_s["company_dollar_cents"] == 282000
        assert small_s["royalty_cents"] == 60000
        assert big_s["company_dollar_cents"] == 846000
        assert big_s["royalty_cents"] == 180000

    def test_window_accumulator_is_order_invariant_total(self, api):
        """PRD §3.6: "only afterward, sixth, are the accumulators increased by
        this deal's company dollar and royalty" — the window total is the sum of
        both postings regardless of which settled first.

        Design: Difficulty/combinatorial_formula/settlement_order_governs_cap_allocation_mode_c
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Oliver Order")
        big = setup_closed_deal(agent["id"], gross_commission_cents=3000000, closing_date="2026-01-10")
        small = setup_closed_deal(agent["id"], gross_commission_cents=1000000, closing_date="2026-01-20")
        api.settle_deal(small["id"], TEST_USERS["transaction_coordinator_headers"])
        api.settle_deal(big["id"], TEST_USERS["transaction_coordinator_headers"])
        w0 = get_window_for_agent(agent["id"], 0)
        assert w0["company_dollar_accrued_cents"] == 1128000


class TestCompanyDollarCapExactThreshold:
    def test_seed_clips_to_exact_cap_then_next_tier_applies(self, api):
        """PRD §3.6 step 4: "The applicable tier is the first tier, in ascending
        threshold order, whose threshold_company_dollar_cents strictly exceeds
        the window's pre-deal company_dollar_accrued_cents; when the accrued
        amount equals a threshold exactly, that tier is exhausted and the next
        tier applies."

        Design: Difficulty/boundary_precision_check/company_dollar_cap_exact_threshold_selects_next_tier
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Bound Betty")
        seed = setup_closed_deal(agent["id"], address="80 Seed St",
                                 gross_commission_cents=8764894, closing_date="2026-01-15")
        seed_s = get_success_data(api.settle_deal(seed["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert seed_s["royalty_cents"] == 300000
        assert seed_s["royalty_capped"] is True
        assert seed_s["company_dollar_cents"] == 2500000
        assert seed_s["cap_clipped"] is True
        follow = setup_closed_deal(agent["id"], address="81 Boundary Rd",
                                   gross_commission_cents=100000, closing_date="2026-01-20")
        s = get_success_data(api.settle_deal(follow["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert s["tier_index_applied"] == 1
        assert s["royalty_cents"] == 0
        assert s["company_dollar_cents"] == 0
        assert s["cap_clipped"] is False
        assert s["agent_gross_cents"] == 100000
        assert s["agent_net_cents"] == 69000

    def test_capping_deal_not_resplit_at_next_tier(self, api):
        """PRD §3.6 step 4: "cap_clipped is true exactly when the cap clipped —
        marking the capping transaction, on which the agent keeps the entire
        surplus above the clipped company dollar and is not re-split at the next
        tier within the same deal."

        Design: Difficulty/boundary_precision_check/company_dollar_cap_exact_threshold_selects_next_tier
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Bound Betty")
        seed = setup_closed_deal(agent["id"], gross_commission_cents=8764894, closing_date="2026-01-15")
        seed_s = get_success_data(api.settle_deal(seed["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert seed_s["cap_clipped"] is True
        assert seed_s["company_dollar_cents"] == 2500000
        # after_royalty = 8764894 - 300000 = 8464894; agent keeps surplus
        assert seed_s["agent_gross_cents"] == 8464894 - 2500000

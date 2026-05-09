"""Difficulty-design coverage: Rule 1 — Dual-variant calculations.

Two instances:
  - order_total_provisional_vs_final
  - leader_chronic_vs_acute_risk_score
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_community, create_supplier, create_customer, create_active_leader,
    create_group_buy_campaign, join_campaign, pay_order, close_campaign,
    recompute_risk, ADMIN, make_group_leader_headers, make_customer_headers,
    create_risk_alert_payload,
)


# ─── Instance 1: order_total_provisional_vs_final ─────────────────────────

class TestOrderTotalProvisionalVsFinal:
    """# difficulty: dual_variant_calc/order_total_provisional_vs_final"""

    def _setup(self):
        community = create_community(region_code="RC1")
        cust1 = create_customer(community["id"], display_name="Cust1")
        cust2 = create_customer(community["id"], display_name="Cust2")
        supplier = create_supplier(name="S1")
        leader = create_active_leader(community["id"], display_name="L1")
        campaign = create_group_buy_campaign(
            leader["id"], supplier["id"],
            sku="SKUA", unit_price_cents=1000,
            discount_tiers=[
                {"min_participants": 1, "discount_basis_points": 500},
                {"min_participants": 2, "discount_basis_points": 1500},
            ],
            opens_at_period=0, deadline_period=100,
        )
        return community, cust1, cust2, supplier, leader, campaign

    def test_provisional_pinned_at_pay_then_settled_pinned_at_close(self, api):
        """PRD §3.3 Order Total: "The provisional variant pins
        provisional_discount_basis_points and provisional_total_cents at the
        moment of payment using the discount-tier-selection result evaluated
        against participant_count as observed when the pay request commits."

        Claim: O1 paid as first participant pins provisional_total=950 (5% off 1000);
        after a second pay raises participant_count to 2 and close pins settled
        tier index 1, O1.settled_total_cents=850.
        """
        community, cust1, cust2, _, leader, campaign = self._setup()

        order1 = join_campaign(campaign["id"], cust1["id"],
                               line_items=[{"sku": "SKUA", "unit_price_cents": 1000, "quantity": 1}])
        order1 = pay_order(order1["id"], cust1["id"])
        assert order1["provisional_discount_basis_points"] == 500
        assert order1["provisional_total_cents"] == 950
        assert order1["subtotal_cents"] == 1000

        order2 = join_campaign(campaign["id"], cust2["id"],
                               line_items=[{"sku": "SKUA", "unit_price_cents": 1000, "quantity": 1}])
        order2 = pay_order(order2["id"], cust2["id"])
        # Now participant_count == 2; O2's provisional uses the tier qualified at its pay time.
        assert order2["provisional_total_cents"] == 850

        campaign_after = close_campaign(campaign["id"], leader["id"])
        assert campaign_after["status"] == "SUCCEEDED"
        assert campaign_after["settled_discount_basis_points"] == 1500

        # Re-fetch O1 — now SETTLED with settled_total_cents=850
        o1_settled = validate_success(api.get_order(order1["id"], ADMIN), 200)
        assert o1_settled["payment_status"] == "SETTLED"
        assert o1_settled["settled_total_cents"] == 850
        # Provisional is preserved for audit
        assert o1_settled["provisional_total_cents"] == 950
        assert o1_settled["provisional_total_cents"] != o1_settled["settled_total_cents"]

    def test_provisional_uses_discount_at_observed_participant_count(self, api):
        """PRD §3.3 Order Total: "The provisional variant pins ...
        provisional_total_cents at the moment of payment using the
        discount-tier-selection result evaluated against participant_count
        as observed when the pay request commits."

        Claim: an order paid at participant_count=1 with [(1,500),(2,1500)]
        discount_tiers pins provisional_discount_basis_points=500.
        """
        _, cust1, _, _, _, campaign = self._setup()
        order1 = join_campaign(campaign["id"], cust1["id"],
                               line_items=[{"sku": "SKUA", "unit_price_cents": 1000, "quantity": 1}])
        order1 = pay_order(order1["id"], cust1["id"])
        assert order1["provisional_discount_basis_points"] == 500
        # 1000 - floor(1000*500/10000) = 1000 - 50 = 950
        assert order1["provisional_total_cents"] == 950


# ─── Instance 2: leader_chronic_vs_acute_risk_score ───────────────────────

class TestLeaderChronicVsAcuteRiskScore:
    """# difficulty: dual_variant_calc/leader_chronic_vs_acute_risk_score"""

    def _setup_with_one_bot_alert(self):
        community = create_community(region_code="RC1")
        cust = create_customer(community["id"], display_name="Cust1")
        supplier = create_supplier(name="S1")
        leader = create_active_leader(community["id"], display_name="L1")
        campaign = create_group_buy_campaign(
            leader["id"], supplier["id"],
            sku="SKUA", unit_price_cents=100,
            discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
            opens_at_period=0, deadline_period=100,
        )
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        # Open + confirm BOT_ORDER alert against this order at period 0
        alert = get_success_data(api_client.create_risk_alert(
            create_risk_alert_payload("BOT_ORDER", "ORDER", order["id"], severity="LOW"),
            ADMIN,
        ))
        get_success_data(api_client.confirm_alert(alert["id"], ADMIN))
        return leader

    def test_chronic_score_uses_30_period_window(self, api):
        """PRD §3.10 Chronic Risk Score: "Each count is divided by 30 to
        obtain its density. The raw chronic score is the bot density
        multiplied by 0.30, plus the fake-group density multiplied by 0.40,
        plus the collusion density multiplied by 0.30, with the resulting
        weighted average then multiplied by 100."

        Claim: with one CONFIRMED BOT_ORDER alert at period 0 and current_period=0,
        chronic = round_half_up(min(0.30 * 1/30 * 100, 100), 2) = 1.00.
        """
        leader = self._setup_with_one_bot_alert()
        recompute_risk()
        leader_after = validate_success(api.get_group_leader(leader["id"], ADMIN), 200)
        assert leader_after["chronic_risk_score"] == pytest.approx(1.00, abs=0.005)

    def test_acute_score_uses_5_period_window_with_15x_multiplier(self, api):
        """PRD §3.10 Acute Risk Score: "the densities divide by 5, the
        weights are 0.50 for bot, 0.30 for fake-group, and 0.20 for
        collusion, and the weighted average (multiplied by 100) is
        additionally multiplied by 1.5."

        Claim: with one CONFIRMED BOT_ORDER alert at period 0, current=0,
        acute = round_half_up(min(0.50 * 1/5 * 100 * 1.5, 100), 2) = 15.00 —
        a different value from the chronic score on the same input.
        """
        leader = self._setup_with_one_bot_alert()
        recompute_risk()
        leader_after = validate_success(api.get_group_leader(leader["id"], ADMIN), 200)
        assert leader_after["acute_risk_score"] == pytest.approx(15.00, abs=0.005)
        assert leader_after["acute_risk_score"] != leader_after["chronic_risk_score"]

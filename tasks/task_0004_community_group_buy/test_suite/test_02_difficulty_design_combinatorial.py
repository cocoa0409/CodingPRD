"""Difficulty-design coverage: Rule 2 — Combinatorial formulas.

Two instances:
  - tiered_rebate_3input_nonlinear
  - tax_withholding_round_per_line_then_sum
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_community, create_supplier, create_customer,
    create_active_leader, create_pending_leader,
    create_group_buy_campaign, join_campaign, pay_order, close_campaign,
    list_commission_entries, find_commission_entry, get_success_data,
    ADMIN, make_group_leader_headers,
)


class TestTieredRebate3InputNonlinear:
    """# difficulty: combinatorial_formula/tiered_rebate_3input_nonlinear"""

    def _build_cross_community_succeeded_campaign(self, settled_total_cents):
        c1 = create_community(region_code="RC1")
        c2 = create_community(region_code="RC2")
        cust1 = create_customer(c1["id"], display_name="Cust1")
        supplier = create_supplier()
        l1 = create_active_leader(c1["id"], display_name="L1")  # tier 1
        # Build a tier-2 leader in c2: parent must be tier 1 in c2
        lp_root = create_active_leader(c2["id"], display_name="LP_root")
        l2 = create_active_leader(c2["id"], parent_leader_id=lp_root["id"], display_name="L2")
        # L2.tier should be 2
        assert l2["tier"] == 2

        campaign = create_group_buy_campaign(
            l1["id"], supplier["id"],
            cross_community_partner_leader_ids=[l2["id"]],
            sku="SKUA", unit_price_cents=settled_total_cents,
            discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
            opens_at_period=0, deadline_period=100,
        )
        order = join_campaign(campaign["id"], cust1["id"],
                              line_items=[{"sku": "SKUA",
                                            "unit_price_cents": settled_total_cents,
                                            "quantity": 1}])
        order = pay_order(order["id"], cust1["id"])
        close_campaign(campaign["id"], l1["id"])
        return l1, l2, order, campaign

    def test_primary_with_secondary_partner_bonus_added(self, api):
        """PRD §3.9 Tiered Rebate: "For a PRIMARY beneficiary, the gross rate
        is the primary rate at the primary's tier plus the secondary bonus
        rate at the cross-community partner's tier (with the bonus rate
        treated as zero when the campaign has no qualifying secondary partner)."

        Claim: primary_tier=1 (800 bp) + cross-community partner tier=2 (100 bp bonus)
        ⇒ gross_rate=900 bp; for settled_total=10000, gross_rebate=floor(10000*900/10000)=900.
        """
        l1, l2, order, _ = self._build_cross_community_succeeded_campaign(10000)
        entry = find_commission_entry(l1["id"], order["id"])
        assert entry is not None, "PRIMARY CommissionEntry must exist for L1"
        assert entry["leader_role"] == "PRIMARY"
        assert entry["gross_rebate_cents"] == 900

    def test_secondary_partner_receives_bonus_rate_only(self, api):
        """PRD §3.9 Tiered Rebate: "For a SECONDARY beneficiary, the gross
        rate is the secondary bonus rate at that secondary partner's tier."

        Claim: SECONDARY beneficiary L2 (tier=2) gets gross_rate=100 bp;
        for settled_total=10000, gross_rebate=floor(10000*100/10000)=100.
        """
        l1, l2, order, _ = self._build_cross_community_succeeded_campaign(10000)
        entry = find_commission_entry(l2["id"], order["id"])
        assert entry is not None, "SECONDARY CommissionEntry must exist for L2"
        assert entry["leader_role"] == "SECONDARY"
        assert entry["gross_rebate_cents"] == 100


class TestTaxWithholdingRoundPerLineThenSum:
    """# difficulty: combinatorial_formula/tax_withholding_round_per_line_then_sum"""

    def _build_two_line_settled_order(self):
        community = create_community(region_code="RC1")
        cust_b = create_customer(community["id"], display_name="CustB")
        cust = create_customer(community["id"], display_name="Cust1")
        supplier = create_supplier()
        l1 = create_active_leader(community["id"], display_name="L1")  # tier 1
        # Bootstrap a SECOND already-SUCCEEDED campaign whose SKU is the
        # cross-group bundled second line of the order under test. PRD requires
        # additional lines to reference the SKU of another SUCCEEDED campaign
        # owned by a leader in the same subtree.
        bundled_campaign = create_group_buy_campaign(
            l1["id"], supplier["id"],
            sku="SKUB", unit_price_cents=100,
            discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
            opens_at_period=0, deadline_period=100,
        )
        bootstrap_order = join_campaign(bundled_campaign["id"], cust_b["id"],
                              line_items=[{"sku": "SKUB", "unit_price_cents": 100, "quantity": 1}])
        pay_order(bootstrap_order["id"], cust_b["id"])
        close_campaign(bundled_campaign["id"], l1["id"])
        # Now the primary campaign (SKUA) — order references SKUA + cross-group SKUB.
        campaign = create_group_buy_campaign(
            l1["id"], supplier["id"],
            sku="SKUA", unit_price_cents=100,
            discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
            opens_at_period=0, deadline_period=100,
        )
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[
                                  {"sku": "SKUA", "unit_price_cents": 100, "quantity": 1},
                                  {"sku": "SKUB", "unit_price_cents": 100, "quantity": 1},
                              ])
        order = pay_order(order["id"], cust["id"])
        close_campaign(campaign["id"], l1["id"])
        return l1, order

    def test_per_line_round_then_sum_picks_2_not_1(self, api):
        """PRD §3.9 Tax Withholding: "The per-line withholding is the per-line
        gross multiplied by 700 basis points and divided by ten thousand,
        rounded half-up to the nearest cent. The entry's tax_withholding_cents
        is the sum of those rounded per-line withholdings (round-per-line,
        then sum — this differs in cents from a sum-then-round computation
        when the per-line products leave fractional residues)."

        Claim: subtotal=200, two equal lines, gross=floor(200*800/10000)=16.
        Per-line gross = 8 + 8. Per-line withholding = round_half_up(8*700/10000)
        = round_half_up(0.56) = 1, summed = 2. Sum-then-round would give
        round_half_up(16*700/10000) = round_half_up(1.12) = 1 (different).
        """
        l1, order = self._build_two_line_settled_order()
        entry = find_commission_entry(l1["id"], order["id"])
        assert entry is not None
        assert entry["gross_rebate_cents"] == 16
        assert entry["tax_withholding_cents"] == 2

    def test_net_rebate_is_gross_minus_withholding(self, api):
        """PRD §3.9 Tax Withholding: "The net_rebate_cents is gross_rebate_cents
        minus tax_withholding_cents."

        Claim: gross=16, withholding=2 ⇒ net=14.
        """
        l1, order = self._build_two_line_settled_order()
        entry = find_commission_entry(l1["id"], order["id"])
        assert entry is not None
        assert entry["net_rebate_cents"] == 14

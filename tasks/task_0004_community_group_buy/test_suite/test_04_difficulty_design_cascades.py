"""Difficulty-design coverage: Rule 4 — Transitive cascade chains.

Two instances:
  - after_sales_refund_to_clawback_chain
  - leader_suspend_to_order_cascade
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_picked_up_order,
    create_community, create_supplier, create_customer, create_active_leader,
    create_group_buy_campaign, join_campaign, pay_order,
    file_after_sales, start_review, resolve_case,
    assemble_payout, find_commission_entry,
    create_risk_alert_payload,
    ADMIN,
)


class TestAfterSalesRefundToClawbackChain:
    """# difficulty: transitive_cascade/after_sales_refund_to_clawback_chain"""

    def _setup_with_payout_and_filed_case(self):
        sc = setup_picked_up_order(unit_price_cents=100, quantity=1)
        order = sc["order"]
        # CommissionEntry: gross=floor(100*800/10000)=8, tax=round_half_up(8*700/10000)=1, net=7
        entry = find_commission_entry(sc["leader"]["id"], order["id"])
        assert entry is not None
        assert entry["gross_rebate_cents"] == 8
        assert entry["tax_withholding_cents"] == 1
        assert entry["net_rebate_cents"] == 7

        payout = assemble_payout(sc["leader"]["id"], entry["payout_target_period_index"])
        assert payout["status"] == "SCHEDULED"
        assert payout["total_amount_cents"] == 7

        case = file_after_sales(order["id"], sc["customer"]["id"],
                                "REFUND_ONLY", 100)
        start_review(case["id"])
        return sc, order, entry, payout, case

    def test_refund_only_resolve_cascades_through_order_entry_payout(self, api):
        """PRD §3.8 REFUND_ONLY branch: "REFUND_ONLY ... synchronously advances
        the parent order's payment_status to REFUND_PENDING ... Every PENDING
        CommissionEntry derived from the order moves to PENDING_CLAWBACK; any
        Payout already bundling those entries has its total_amount_cents
        recomputed with the clawback-flagged entries excluded from the total
        while bundled_entry_ids is preserved for audit."

        Claim: after resolve REFUND_ONLY, the chain Order → CommissionEntry →
        Payout shows REFUND_PENDING + PENDING_CLAWBACK + total_amount_cents=0.
        """
        sc, order, entry, payout, case = self._setup_with_payout_and_filed_case()

        case_after = resolve_case(case["id"], "REFUND_ONLY")
        assert case_after["status"] == "RESOLVED_REFUND_ONLY"

        order_after = validate_success(api.get_order(order["id"], ADMIN), 200)
        assert order_after["payment_status"] == "REFUND_PENDING"

        entry_after = find_commission_entry(sc["leader"]["id"], order["id"])
        assert entry_after["status"] == "PENDING_CLAWBACK"

        payout_after = validate_success(api.get_payout(payout["id"], ADMIN), 200)
        assert payout_after["total_amount_cents"] == 0
        assert payout_after["status"] == "SCHEDULED"

    def test_payout_bundled_entry_ids_preserved_after_clawback_flag(self, api):
        """PRD §3.8 REFUND_ONLY: "any Payout already bundling those entries
        has its total_amount_cents recomputed with the clawback-flagged
        entries excluded from the total while bundled_entry_ids is preserved
        for audit."

        Claim: after the cascade, the Payout's bundled_entry_ids still
        contains the clawed entry id (audit retention).
        """
        sc, order, entry, payout, case = self._setup_with_payout_and_filed_case()
        resolve_case(case["id"], "REFUND_ONLY")
        payout_after = validate_success(api.get_payout(payout["id"], ADMIN), 200)
        assert entry["id"] in payout_after["bundled_entry_ids"]


class TestLeaderSuspendToOrderCascade:
    """# difficulty: transitive_cascade/leader_suspend_to_order_cascade"""

    def _setup_with_paid_order_and_open_alert(self):
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
        order = pay_order(order["id"], cust["id"])
        alert = get_success_data(api_client.create_risk_alert(
            create_risk_alert_payload(
                "LEADER_SUPPLIER_COLLUSION", "GROUP_LEADER", leader["id"],
                severity="HIGH", supporting_supplier_id=supplier["id"],
            ),
            ADMIN,
        ))
        return leader, campaign, order, alert

    def test_alert_confirm_cascades_to_leader_suspend_campaign_fail_order_refund(self, api):
        """PRD §3.10: "Confirming an alert advances status to CONFIRMED ...
        When the alert is LEADER_SUPPLIER_COLLUSION against a GROUP_LEADER,
        or when its severity is HIGH against a GROUP_LEADER, the targeted
        GroupLeader advances from ACTIVE to SUSPENDED (with the
        leader-suspension cascade described under §3.1 firing)."
        PRD §3.1: "every FORMING and EXTENDED GroupBuyCampaign whose
        leader_id is the suspended leader auto-closes as FAILED."
        PRD §3.3 FAILED branch: "every child Order whose payment_status was
        PAID flows through the auto-refund cascade — payment_status advances
        from PAID to REFUND_PENDING ... the order's fulfillment_status is
        set to CANCELLED from NOT_PLANNED".

        Claim: the depth-3 cascade observable end-to-end via one /confirm call.
        """
        leader, campaign, order, alert = self._setup_with_paid_order_and_open_alert()
        get_success_data(api_client.confirm_alert(alert["id"], ADMIN))

        leader_after = validate_success(api.get_group_leader(leader["id"], ADMIN), 200)
        assert leader_after["status"] == "SUSPENDED"

        campaign_after = validate_success(api.get_group_buy_campaign(campaign["id"], ADMIN), 200)
        assert campaign_after["status"] == "FAILED"

        order_after = validate_success(api.get_order(order["id"], ADMIN), 200)
        assert order_after["payment_status"] == "REFUND_PENDING"
        assert order_after["fulfillment_status"] == "CANCELLED"

    def test_collusion_audit_count_incremented_on_confirm(self, api):
        """PRD §3.10: "When the alert is LEADER_SUPPLIER_COLLUSION against a
        GROUP_LEADER, the targeted leader's collusion_audit_count is
        increased by exactly one."

        Claim: confirming a LEADER_SUPPLIER_COLLUSION alert against a leader
        bumps that leader's collusion_audit_count by one.
        """
        leader, campaign, order, alert = self._setup_with_paid_order_and_open_alert()
        before = leader["collusion_audit_count"]
        get_success_data(api_client.confirm_alert(alert["id"], ADMIN))
        leader_after = validate_success(api.get_group_leader(leader["id"], ADMIN), 200)
        assert leader_after["collusion_audit_count"] == before + 1

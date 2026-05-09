"""Difficulty-design coverage: Rule 8 — Resource temporal-overlap conflicts.

Two instances:
  - pickup_consolidation_buffered_closed_interval
  - campaign_per_community_sku_half_open_interval
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_community, create_supplier, create_customer, create_active_leader,
    create_pickup_point, create_warehouse, create_group_buy_campaign,
    join_campaign, pay_order, close_campaign,
    setup_paid_succeeded_order,
    plan_shipments_for_order, dispatch_shipment, arrive_shipment,
    create_consolidation_batch_payload,
    create_group_buy_campaign_payload,
    ADMIN, PICKUP_OP, make_group_leader_headers, make_supplier_headers,
)


class TestPickupConsolidationBufferedClosedInterval:
    """# difficulty: resource_temporal_overlap/pickup_consolidation_buffered_closed_interval"""

    def _setup_two_at_pickup_shipments(self):
        community = create_community(region_code="RC1")
        cust1 = create_customer(community["id"], display_name="Cust1")
        cust2 = create_customer(community["id"], display_name="Cust2")
        supplier = create_supplier(name="S1")
        create_warehouse(supplier["id"], region_code="RC1")
        leader = create_active_leader(community["id"], display_name="L1")
        pickup = create_pickup_point(community["id"], capacity_packages=5,
                                       cold_storage_capable=False)
        campaign = create_group_buy_campaign(
            leader["id"], supplier["id"],
            sku="SKUA", unit_price_cents=100,
            discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
            opens_at_period=0, deadline_period=100,
        )
        o1 = join_campaign(campaign["id"], cust1["id"],
                           line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        o1 = pay_order(o1["id"], cust1["id"])
        o2 = join_campaign(campaign["id"], cust2["id"],
                           line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        o2 = pay_order(o2["id"], cust2["id"])
        close_campaign(campaign["id"], leader["id"])
        sh1_list = plan_shipments_for_order(o1["id"], supplier["id"], pickup["id"],
                                             [{"sku": "SKUA", "quantity": 1}])
        sh2_list = plan_shipments_for_order(o2["id"], supplier["id"], pickup["id"],
                                             [{"sku": "SKUA", "quantity": 1}])
        sh1, sh2 = sh1_list[0], sh2_list[0]
        dispatch_shipment(sh1["id"], supplier["id"])
        dispatch_shipment(sh2["id"], supplier["id"])
        arrive_shipment(sh1["id"], supplier["id"])
        arrive_shipment(sh2["id"], supplier["id"])
        return pickup, sh1, sh2

    def test_buffered_window_overlap_rejected(self, api):
        """PRD §3.7: "the platform expands each batch's window by a buffer
        of one period on each side (so the registered closed interval runs
        from window_start_period minus one to window_end_period plus one)
        and rejects any new batch whose buffered window intersects any
        existing batch on the same pickup point with ERR_CONSOLIDATION_WINDOW_OVERLAP."

        Claim: B1=[3,5] (effective [2,6]) and B2=[6,10] (effective [5,11])
        share period 5 and 6 — second batch is rejected with
        ERR_CONSOLIDATION_WINDOW_OVERLAP.
        """
        pickup, sh1, sh2 = self._setup_two_at_pickup_shipments()
        get_success_data(api_client.create_consolidation_batch(
            pickup["id"],
            create_consolidation_batch_payload(3, 5, [sh1["id"]]),
            PICKUP_OP,
        ))
        res = api.create_consolidation_batch(
            pickup["id"],
            create_consolidation_batch_payload(6, 10, [sh2["id"]]),
            PICKUP_OP,
        )
        validate_error(res, "ERR_CONSOLIDATION_WINDOW_OVERLAP")

    def test_non_overlapping_windows_both_succeed(self, api):
        """PRD §3.7: "the platform expands each batch's window by a buffer
        of one period on each side ... and rejects any new batch whose
        buffered window intersects any existing batch on the same pickup point".

        Claim: B1=[1,2] (effective [0,3]) and B2=[5,6] (effective [4,7])
        do NOT share any period — both are accepted.
        """
        pickup, sh1, sh2 = self._setup_two_at_pickup_shipments()
        b1 = get_success_data(api_client.create_consolidation_batch(
            pickup["id"],
            create_consolidation_batch_payload(1, 2, [sh1["id"]]),
            PICKUP_OP,
        ))
        b2 = get_success_data(api_client.create_consolidation_batch(
            pickup["id"],
            create_consolidation_batch_payload(5, 6, [sh2["id"]]),
            PICKUP_OP,
        ))
        assert b1["status"] == "OPEN"
        assert b2["status"] == "OPEN"


class TestCampaignPerCommunitySkuHalfOpenInterval:
    """# difficulty: resource_temporal_overlap/campaign_per_community_sku_half_open_interval"""

    def _setup_one_campaign(self):
        community = create_community(region_code="RC1")
        supplier = create_supplier(name="S1")
        leader = create_active_leader(community["id"], display_name="L1")
        get_success_data(api_client.create_group_buy_campaign(
            leader["id"],
            create_group_buy_campaign_payload(
                supplier["id"],
                sku="SKUA", unit_price_cents=100,
                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                opens_at_period=0, deadline_period=10,
            ),
            make_group_leader_headers(leader["id"]),
        ))
        return leader, supplier

    def test_adjacent_half_open_window_allowed(self, api):
        """PRD §3.3: "Adjacent windows where one campaign's deadline_period
        equals the next campaign's opens_at_period are explicitly permitted
        because the interval is half-open."

        Claim: K1 with deadline_period=10 does not block K2 with
        opens_at_period=10 — the second campaign is created (HTTP 201).
        """
        leader, supplier = self._setup_one_campaign()
        res = api.create_group_buy_campaign(
            leader["id"],
            create_group_buy_campaign_payload(
                supplier["id"],
                sku="SKUA", unit_price_cents=100,
                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                opens_at_period=10, deadline_period=20,
            ),
            make_group_leader_headers(leader["id"]),
        )
        validate_success(res, 201)

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "When the creating leader's community already holds a
        campaign on the same sku whose half-open window between
        opens_at_period (inclusive) and deadline_period (exclusive)
        intersects the proposed window, and that existing campaign is in
        FORMING, EXTENDED, or SUCCEEDED, the new request is rejected with
        ERR_COMMUNITY_CAMPAIGN_OVERLAP."

        Claim: K1=[0,10) overlapping with K3=[9,19) shares period 9 — K3 is
        rejected with ERR_COMMUNITY_CAMPAIGN_OVERLAP.
        """
        leader, supplier = self._setup_one_campaign()
        res = api.create_group_buy_campaign(
            leader["id"],
            create_group_buy_campaign_payload(
                supplier["id"],
                sku="SKUA", unit_price_cents=100,
                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                opens_at_period=9, deadline_period=19,
            ),
            make_group_leader_headers(leader["id"]),
        )
        validate_error(res, "ERR_COMMUNITY_CAMPAIGN_OVERLAP")

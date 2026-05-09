"""Difficulty-design coverage: Rule 6 — Boundary-precision checks.

Two instances:
  - discount_tier_threshold_inclusive
  - pickup_point_capacity_inclusive_full_rejects
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_community, create_supplier, create_customer, create_active_leader,
    create_pickup_point, create_warehouse, create_group_buy_campaign,
    join_campaign, pay_order, close_campaign,
    setup_multi_customer_paid,
    plan_shipments_for_order, dispatch_shipment,
    ADMIN, make_supplier_headers,
)


class TestDiscountTierThresholdInclusive:
    """# difficulty: boundary_precision_check/discount_tier_threshold_inclusive"""

    def test_participant_count_equal_to_min_qualifies_tier(self, api):
        """PRD §3.3 Discount-Tier Selection: "Tier qualification is inclusive
        on min_participants: a participant_count exactly equal to a tier's
        min_participants qualifies for that tier."

        Claim: with discount_tiers=[{min:5, bp:1000},{min:10, bp:2000}] and
        exactly 5 paid participants at close, settled_tier_index=0 and
        settled_discount_basis_points=1000.
        """
        sc = setup_multi_customer_paid(
            num_customers=5, unit_price_cents=100,
            discount_tiers=[
                {"min_participants": 5, "discount_basis_points": 1000},
                {"min_participants": 10, "discount_basis_points": 2000},
            ],
        )
        campaign_after = close_campaign(sc["campaign"]["id"], sc["leader"]["id"])
        assert campaign_after["status"] == "SUCCEEDED"
        assert campaign_after["settled_tier_index"] == 0
        assert campaign_after["settled_discount_basis_points"] == 1000

    def test_largest_qualifying_min_participants_chosen(self, api):
        """PRD §3.3 Discount-Tier Selection: "Given the current
        participant_count, the platform considers every discount_tiers entry
        whose min_participants is at most participant_count; among those
        qualifying tiers, the platform picks the entry with the largest
        min_participants and uses that entry's index (zero-based) as
        settled_tier_index and that entry's discount_basis_points as
        settled_discount_basis_points."

        Claim: with discount_tiers=[{min:1, bp:500},{min:2, bp:1500}] and 2
        participants, settled tier index is 1 (the larger qualifying min).
        """
        sc = setup_multi_customer_paid(
            num_customers=2, unit_price_cents=100,
            discount_tiers=[
                {"min_participants": 1, "discount_basis_points": 500},
                {"min_participants": 2, "discount_basis_points": 1500},
            ],
        )
        campaign_after = close_campaign(sc["campaign"]["id"], sc["leader"]["id"])
        assert campaign_after["status"] == "SUCCEEDED"
        assert campaign_after["settled_tier_index"] == 1
        assert campaign_after["settled_discount_basis_points"] == 1500


class TestPickupPointCapacityInclusiveFullRejects:
    """# difficulty: boundary_precision_check/pickup_point_capacity_inclusive_full_rejects"""

    def _setup_two_orders_one_capacity_pickup(self):
        community = create_community(region_code="RC1")
        cust1 = create_customer(community["id"], display_name="Cust1")
        cust2 = create_customer(community["id"], display_name="Cust2")
        supplier = create_supplier(name="S1")
        create_warehouse(supplier["id"], region_code="RC1")
        leader = create_active_leader(community["id"], display_name="L1")
        pickup = create_pickup_point(community["id"], capacity_packages=1,
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
        sh1 = sh1_list[0]
        sh2 = sh2_list[0]
        dispatch_shipment(sh1["id"], supplier["id"])
        dispatch_shipment(sh2["id"], supplier["id"])
        # First arrival fills capacity (held=1 after, exactly == capacity)
        get_success_data(api_client.arrive_at_pickup(sh1["id"], make_supplier_headers(supplier["id"])))
        return supplier, pickup, sh1, sh2

    def test_second_arrival_at_capacity_full_rejected(self, api):
        """PRD §3.6 arrive-at-pickup: "the destination's held_package_count
        plus one must be at most capacity_packages — that is, the destination
        strictly enforces the boundary inclusively, so held_package_count may
        equal capacity_packages after the increment but never exceed it; a
        request that would push the held count to capacity_packages plus one
        is rejected with ERR_PICKUP_POINT_AT_CAPACITY."

        Claim: with capacity=1 and held=1 after the first arrival, the
        second arrival is rejected with ERR_PICKUP_POINT_AT_CAPACITY.
        """
        supplier, pickup, sh1, sh2 = self._setup_two_orders_one_capacity_pickup()
        res = api.arrive_at_pickup(sh2["id"], make_supplier_headers(supplier["id"]))
        validate_error(res, "ERR_PICKUP_POINT_AT_CAPACITY")

    def test_held_count_unchanged_after_rejected_arrival(self, api):
        """PRD §3.6 arrive-at-pickup: "a request that would push the held
        count to capacity_packages plus one is rejected with
        ERR_PICKUP_POINT_AT_CAPACITY."

        Claim: when the second arrival is rejected, the pickup point's
        held_package_count remains at the pre-attempt value (1), not 2.
        """
        supplier, pickup, sh1, sh2 = self._setup_two_orders_one_capacity_pickup()
        api.arrive_at_pickup(sh2["id"], make_supplier_headers(supplier["id"]))  # rejected
        summary = validate_success(api.get_pickup_point_summary(pickup["id"], ADMIN), 200)
        assert summary["held_package_count"] == 1
        assert summary["capacity_packages"] == 1

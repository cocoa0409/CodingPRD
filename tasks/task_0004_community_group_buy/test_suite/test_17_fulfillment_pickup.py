"""Fulfilment: ETA prediction, pickup-confirm, capacity boundary, cold-storage incompat."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_paid_succeeded_order, setup_picked_up_order,
    create_community, create_supplier, create_customer, create_active_leader,
    create_pickup_point, create_warehouse, create_group_buy_campaign,
    join_campaign, pay_order, close_campaign,
    plan_shipments_for_order, dispatch_shipment, arrive_shipment,
    create_plan_shipments_payload,
    THRESHOLDS,
    ADMIN, make_customer_headers, make_supplier_headers,
)


class TestShipmentEtaPrediction:

    def test_dispatch_pins_eta_using_handling_periods(self, api):
        """PRD §3.6: "Predicted ETA is dispatched_period_index plus the
        warehouse's cold_handling_periods when cold_chain_segment is true
        and dispatched_period_index plus the warehouse's handling_periods
        otherwise."

        Claim: for a non-cold shipment from a warehouse with
        handling_periods=3, predicted_eta_period_index = dispatched_period_index + 3.
        """
        community = create_community(region_code="RC1")
        cust = create_customer(community["id"], display_name="C")
        supplier = create_supplier()
        # warehouse with handling_periods=3
        wh = create_warehouse(supplier["id"], region_code="RC1",
                                cold_chain_capable=False, handling_periods=3,
                                cold_handling_periods=1)
        leader = create_active_leader(community["id"], display_name="L")
        pickup = create_pickup_point(community["id"], capacity_packages=5,
                                       cold_storage_capable=False)
        campaign = create_group_buy_campaign(leader["id"], supplier["id"],
                                                unit_price_cents=100,
                                                discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
                                                opens_at_period=0, deadline_period=10000)
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[{"sku": "SKUA", "unit_price_cents": 100, "quantity": 1}])
        order = pay_order(order["id"], cust["id"])
        close_campaign(campaign["id"], leader["id"])
        shipments = plan_shipments_for_order(order["id"], supplier["id"], pickup["id"],
                                                [{"sku": "SKUA", "quantity": 1}])
        sh = shipments[0]
        dispatched = validate_success(api.dispatch_shipment(sh["id"],
                                                              make_supplier_headers(supplier["id"])),
                                        200)
        assert dispatched["predicted_eta_period_index"] == dispatched["dispatched_period_index"] + 3


class TestPickupConfirmFlow:

    def test_pickup_confirm_advances_order_and_shipments(self, api):
        """PRD §3.6: "The transition advances the order's fulfillment_status
        from AT_PICKUP to PICKED_UP and moves every child shipment to
        DELIVERED, decrementing the destination's held_package_count by
        exactly one per shipment."

        Claim: pickup-confirm advances order to PICKED_UP and child
        shipment to DELIVERED, and decrements held_package_count.
        """
        sc = setup_paid_succeeded_order(unit_price_cents=100, quantity=1)
        shipments = plan_shipments_for_order(
            sc["order"]["id"], sc["supplier"]["id"], sc["pickup_point"]["id"],
            [{"sku": "SKUA", "quantity": 1}],
        )
        sh = shipments[0]
        dispatch_shipment(sh["id"], sc["supplier"]["id"])
        arrive_shipment(sh["id"], sc["supplier"]["id"])

        summary_before = validate_success(api.get_pickup_point_summary(sc["pickup_point"]["id"], ADMIN), 200)
        assert summary_before["held_package_count"] == 1

        order_after = validate_success(api.pickup_confirm(sc["order"]["id"],
                                                            make_customer_headers(sc["customer"]["id"])),
                                         200)
        assert order_after["fulfillment_status"] == "PICKED_UP"
        sh_after = validate_success(api.get_shipment(sh["id"], ADMIN), 200)
        assert sh_after["status"] == "DELIVERED"
        summary_after = validate_success(api.get_pickup_point_summary(sc["pickup_point"]["id"], ADMIN), 200)
        assert summary_after["held_package_count"] == 0


class TestColdChainPickupIncompatibility:

    def test_cold_segment_at_non_cold_pickup_rejected(self, api):
        """PRD §3.6: "when cold_chain_segment is true, the destination must
        have cold_storage_capable set to true; otherwise the rejection is
        ERR_PICKUP_POINT_COLD_INCOMPATIBLE."

        Claim: arriving a cold-chain shipment at a pickup point with
        cold_storage_capable=False is rejected with ERR_PICKUP_POINT_COLD_INCOMPATIBLE.
        """
        community = create_community(name="C-COLDPP", region_code="RC1")
        cust = create_customer(community["id"], display_name="C")
        supplier = create_supplier(name="S")
        wh = create_warehouse(supplier["id"], region_code="RC1",
                                cold_chain_capable=True)
        leader = create_active_leader(community["id"], display_name="L")
        # Non-cold pickup point
        pickup = create_pickup_point(community["id"], capacity_packages=5,
                                       cold_storage_capable=False)
        campaign = create_group_buy_campaign(
            leader["id"], supplier["id"],
            sku="COLD2", cold_chain_required=True,
            unit_price_cents=100,
            discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
            opens_at_period=0, deadline_period=100,
        )
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[{"sku": "COLD2", "unit_price_cents": 100, "quantity": 1}])
        order = pay_order(order["id"], cust["id"])
        close_campaign(campaign["id"], leader["id"])
        shipments = plan_shipments_for_order(order["id"], supplier["id"], pickup["id"],
                                                [{"sku": "COLD2", "quantity": 1}])
        sh = shipments[0]
        dispatch_shipment(sh["id"], supplier["id"])
        res = api.arrive_at_pickup(sh["id"], make_supplier_headers(supplier["id"]))
        validate_error(res, "ERR_PICKUP_POINT_COLD_INCOMPATIBLE")


class TestPickupSummaryLoadState:

    def test_pickup_summary_load_state_thresholds(self, api):
        """PRD §3.7: "The load state derived from that factor is HEALTHY
        while the factor is below 0.75, ELEVATED when the factor is at
        least 0.75 and below 1.00, and FULL when the factor is at or
        above 1.00."

        Claim: with capacity=4 and held=0, load_state is HEALTHY.
        """
        community = create_community(name="C-LS", region_code="RC1")
        pp = create_pickup_point(community["id"], capacity_packages=4, cold_storage_capable=True)
        summary = validate_success(api.get_pickup_point_summary(pp["id"], ADMIN), 200)
        assert summary["held_package_count"] == 0
        assert summary["capacity_packages"] == 4
        assert summary["load_state"] == "HEALTHY"

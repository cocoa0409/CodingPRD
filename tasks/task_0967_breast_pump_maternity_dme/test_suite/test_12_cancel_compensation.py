"""Cancel compensation: pump/garment allowance conservation, prescription restore."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_garment_item,
    setup_pending_order_verified,
    setup_qualified_order,
    validate_success,
)


class TestPumpAllowanceConservation:
    def test_qualify_consumes_pump_allowance_and_prescription(
        self, api, insurance_specialist_headers, care_coordinator_headers
    ):
        """PRD §3.3: "Qualification also consumes budgets: the policy's
        `pumps_consumed_count` rises by 1, its `garments_consumed_count` rises by the
        order's total garment quantity, and the supporting prescription cascades
        `VERIFIED → CONSUMED` with `consumed_by_order_id` pointing at this order."

        Design: Difficulty/compensating_invariant/pump_allowance_qualify_cancel_conservation
        """
        ctx = setup_qualified_order(policy_overrides={"pump_allowance_per_period": 1})
        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["pumps_consumed_count"] == 1
        rx = validate_success(
            api.get_prescription(ctx["rx"]["id"], care_coordinator_headers), 200
        )
        assert rx["status"] == "CONSUMED"
        assert rx["consumed_by_order_id"] == ctx["order"]["id"]

    def test_cancel_of_qualified_order_restores_allowance_and_prescription(
        self, api, care_coordinator_headers
    ):
        """PRD §3.8: "Cancelling a `QUALIFIED` order runs full compensation: the policy's
        `pumps_consumed_count` decreases by 1 and its `garments_consumed_count` decreases
        by the order's garment quantity; the consumed prescription is restored
        `CONSUMED → VERIFIED` with `consumed_by_order_id` cleared to null".

        Design: Difficulty/compensating_invariant/pump_allowance_qualify_cancel_conservation
        """
        ctx = setup_qualified_order(policy_overrides={"pump_allowance_per_period": 1})
        cancelled = validate_success(
            api.cancel_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"

        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["pumps_consumed_count"] == 0
        rx = validate_success(
            api.get_prescription(ctx["rx"]["id"], care_coordinator_headers), 200
        )
        assert rx["status"] == "VERIFIED"
        assert rx["consumed_by_order_id"] is None


class TestGarmentConsumptionReversal:
    def test_qualify_counts_garments_and_cancel_releases_them(
        self, api, care_coordinator_headers
    ):
        """PRD §2.7: "The invariant maintained at all times is that
        `garments_consumed_count` equals the sum of garment-line quantities over the
        policy's orders whose fulfillment is `QUALIFIED`, `SHIPPED`, or `DELIVERED`;
        consumption happens at qualification and is released at cancellation."

        Design: Corner/calculations/garment_consumption_reversal_on_cancel
        """
        garment = create_garment_item()
        ctx = setup_pending_order_verified(
            policy_overrides={"garment_allowance_per_period": 4}
        )
        validate_success(
            api.add_order_line(ctx["order"]["id"],
                               {"catalog_item_id": garment["id"], "quantity": 2},
                               care_coordinator_headers), 201
        )
        qualified = validate_success(
            api.qualify_pump_order(ctx["order"]["id"],
                                   TEST_USERS["insurance_specialist_headers"]), 200
        )
        assert qualified["fulfillment_status"] == "QUALIFIED"

        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["garments_consumed_count"] == 2
        assert policy["pumps_consumed_count"] == 1

        validate_success(api.cancel_pump_order(ctx["order"]["id"], care_coordinator_headers),
                         200)
        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["garments_consumed_count"] == 0
        assert policy["pumps_consumed_count"] == 0

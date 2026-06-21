"""Cross-entity state-dependency depth tests: an operation on entity A is gated by the
state of a referenced entity B.

Translates queue-A difficulty instances under rule_id cross_entity_state_dependency.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_active_layaway_plan,
    create_layaway_plan,
    create_trade_in_offer,
    create_customer,
    suspend_customer,
    ApiErrorId,
    TEST_USERS,
    api_client,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


class TestLayawayItemAvailability:
    def test_activate_second_plan_on_reserved_item_rejected(self, api):
        """PRD §3.5: "Activation is legal only from `PENDING`, and it additionally requires
        that the reserved item is currently `IN_STOCK`; an item that is not in stock rejects
        activation with `ERR_ITEM_NOT_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/layaway_activate_requires_item_in_stock
        """
        # First plan reserves the item; a second PENDING plan on the same item must fail.
        first_plan, _, item = create_active_layaway_plan(
            item_price_cents=500000, installment_count=4
        )
        item_after = validate_success_get_item(api, item["id"])
        second_customer = create_customer()
        second_plan, _, _ = create_layaway_plan(
            customer_id=second_customer["id"],
            inventory_item_id=item["id"],
            installment_count=4,
        )
        res = api.activate_layaway_plan(
            second_plan["id"], {"expected_inventory_item_version": item_after["version"]}, SA
        )
        validate_error(res, ApiErrorId.ERR_ITEM_NOT_AVAILABLE.value, expected_status=409)

    def test_reserved_item_blocks_layaway_activation(self, api):
        """PRD §3.5: "an item that is not in stock rejects activation with
        `ERR_ITEM_NOT_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/layaway_activate_requires_item_in_stock
        """
        first_plan, _, item = create_active_layaway_plan(
            item_price_cents=500000, installment_count=4
        )
        item_after = validate_success_get_item(api, item["id"])
        assert item_after["status"] == "RESERVED"
        second_customer = create_customer()
        second_plan, _, _ = create_layaway_plan(
            customer_id=second_customer["id"],
            inventory_item_id=item["id"],
            installment_count=4,
        )
        res = api.activate_layaway_plan(
            second_plan["id"], {"expected_inventory_item_version": item_after["version"]}, SA
        )
        validate_error(res, ApiErrorId.ERR_ITEM_NOT_AVAILABLE.value, expected_status=409)


class TestTradeInCustomerStatus:
    def test_accept_offer_for_suspended_customer_rejected(self, api):
        """PRD §3.6: "Accepting transitions `OFFERED → ACCEPTED` and additionally requires
        that the customer is `ACTIVE`; a suspended customer rejects acceptance with
        `ERR_CUSTOMER_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/tradein_accept_requires_customer_active
        """
        customer = create_customer()
        offer, _ = create_trade_in_offer(
            customer_id=customer["id"],
            metal_karat="K24",
            metal_weight_grams=10.0,
            metal_spot_price_cents_per_gram=7000,
            gemstone_value_cents=0,
            condition="EXCELLENT",
        )
        suspend_customer(customer)
        res = api.accept_trade_in(offer["id"], {"expected_version": offer["version"]}, SM)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_SUSPENDED.value, expected_status=409)

    def test_suspended_customer_blocks_trade_in_accept(self, api):
        """PRD §3.6: "a suspended customer rejects acceptance with `ERR_CUSTOMER_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/tradein_accept_requires_customer_active
        """
        customer = create_customer()
        offer, _ = create_trade_in_offer(
            customer_id=customer["id"],
            metal_karat="K24",
            metal_weight_grams=10.0,
            metal_spot_price_cents_per_gram=7000,
            gemstone_value_cents=0,
            condition="EXCELLENT",
        )
        suspend_customer(customer)
        res = api.accept_trade_in(offer["id"], {"expected_version": offer["version"]}, SM)
        validate_error(res, ApiErrorId.ERR_CUSTOMER_SUSPENDED.value, expected_status=409)


def validate_success_get_item(api, item_id):
    """Fetch the current inventory item (manager-readable)."""
    return validate_success(api.get_inventory_item(item_id, SM), 200)

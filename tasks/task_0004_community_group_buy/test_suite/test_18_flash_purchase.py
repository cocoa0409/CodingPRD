"""Flash purchase: order shape, inventory updates, customer status checks."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_flash_scenario,
    create_flash_purchase_payload,
    assert_flash_inventory_invariant,
    ADMIN, make_customer_headers,
)


class TestFlashPurchaseHappyPath:

    def test_purchase_creates_settled_flash_order(self, api):
        """PRD §3.5: "creates an Order with campaign_kind set to FLASH ...
        payment_status set directly to SETTLED, and fulfillment_status set
        to NOT_PLANNED."

        Claim: a successful flash purchase creates an Order with
        campaign_kind=FLASH, payment_status=SETTLED, fulfillment_status=NOT_PLANNED.
        """
        sc = setup_flash_scenario(total_stock=10, tier_caps=[{"tier": 0, "max_units": 5}],
                                    unit_price_cents=100)
        res = api.flash_purchase(
            sc["flash_campaign"]["id"],
            create_flash_purchase_payload(requested_units=2),
            make_customer_headers(sc["customer"]["id"]),
        )
        order = validate_success(res, 201)
        assert order["campaign_kind"] == "FLASH"
        assert order["payment_status"] == "SETTLED"
        assert order["fulfillment_status"] == "NOT_PLANNED"
        assert order["flash_granted_units"] == 2
        # subtotal = 100 * 2 = 200; settled_total = subtotal (no discount on flash)
        assert order["subtotal_cents"] == 200
        assert order["settled_total_cents"] == 200

    def test_inventory_decremented_after_purchase(self, api):
        """PRD §3.5: "On a successful purchase, the platform increases
        allocated_units by the granted amount, decreases remaining_units
        by the same amount".

        Claim: after buying 3 units from a 10-stock campaign,
        allocated_units=3 and remaining_units=7.
        """
        sc = setup_flash_scenario(total_stock=10, tier_caps=[{"tier": 0, "max_units": 5}])
        get_success_data(api.flash_purchase(
            sc["flash_campaign"]["id"],
            create_flash_purchase_payload(requested_units=3),
            make_customer_headers(sc["customer"]["id"]),
        ))
        fc_after = get_success_data(api.get_flash_campaign(sc["flash_campaign"]["id"], ADMIN))
        assert fc_after["allocated_units"] == 3
        assert fc_after["remaining_units"] == 7
        assert_flash_inventory_invariant(fc_after)


class TestFlashCancelInventoryRollback:

    def test_cancel_flash_order_restores_inventory(self, api):
        """PRD §3.5: "if the campaign's status was EXHAUSTED, the current
        period is still below closes_at_period, and remaining_units is now
        greater than zero, the campaign returns to OPEN."

        Claim: after exhausting stock and then cancelling the order, the
        flash campaign returns from EXHAUSTED to OPEN.
        """
        sc = setup_flash_scenario(total_stock=1, tier_caps=[{"tier": 0, "max_units": 5}])
        order = get_success_data(api.flash_purchase(
            sc["flash_campaign"]["id"],
            create_flash_purchase_payload(requested_units=1),
            make_customer_headers(sc["customer"]["id"]),
        ))
        fc_after_purchase = get_success_data(api.get_flash_campaign(sc["flash_campaign"]["id"], ADMIN))
        assert fc_after_purchase["status"] == "EXHAUSTED"

        get_success_data(api.cancel_order(order["id"], make_customer_headers(sc["customer"]["id"])))
        fc_after_cancel = get_success_data(api.get_flash_campaign(sc["flash_campaign"]["id"], ADMIN))
        assert fc_after_cancel["status"] == "OPEN"
        assert fc_after_cancel["remaining_units"] == 1

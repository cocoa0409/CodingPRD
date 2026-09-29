"""Observation-date variants of the contract settlement price (PRD §3.4)."""

from test_helpers import (
    api_client,
    read_order,
    read_order_line,
    setup_indexed_contract_delivered_order,
    validate_success,
)
from test_helpers.fixtures import PC


class TestDeliveryDateIndexSettlement:
    """`DELIVERY_DATE_INDEX` settles on the delivery-date observation."""

    def test_provisional_submission_prices_at_the_order_date_quote(self):
        """PRD §3.4: "During submission and during every provisional reprice, the
        observation date is the order's `order_placed_on`, regardless of what the
        contract's `pricing_mode` says."

        The order is placed on 2026-08-05, so the 2026-07-01 quote of 38 c/lb is
        prevailing and the 2026-09-10 quote of 47 c/lb is ignored: 38 + basis 6
        gives 44 c/lb.

        Design: Difficulty/dual_variant_calc/dual_variant_flour_price_provisional_order_date_vs_final_delivery_date_index
        """
        scenario = setup_indexed_contract_delivered_order(
            pricing_mode="DELIVERY_DATE_INDEX", deliver=False
        )
        provisional = scenario["provisional_order"]
        assert provisional["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL after submit, got {provisional['pricing_status']}"
        )
        assert provisional["subtotal_cents"] == 853600, (
            f"Expected subtotal 853600 at 44 c/lb, got {provisional['subtotal_cents']}"
        )
        assert provisional["total_cents"] == 866404, (
            f"Expected provisional total 866404, got {provisional['total_cents']}"
        )

    def test_final_settlement_reprices_at_the_delivery_date_quote(self):
        """PRD §3.4: "During final settlement, the observation date depends on the
        mode: under `DELIVERY_DATE_INDEX` it is the order's `delivered_on`, and
        under `ORDER_DATE_INDEX` it remains `order_placed_on`."

        Delivery lands on 2026-09-15, so the 2026-09-10 quote of 47 c/lb becomes
        prevailing and the settled price rises to 47 + 6 = 53 c/lb.

        Design: Difficulty/dual_variant_calc/dual_variant_flour_price_provisional_order_date_vs_final_delivery_date_index
        """
        scenario = setup_indexed_contract_delivered_order(
            pricing_mode="DELIVERY_DATE_INDEX", deliver=True
        )
        provisional_total = scenario["provisional_order"]["total_cents"]

        final_order = validate_success(
            api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC)
        )

        assert final_order["pricing_status"] == "FINAL", (
            f"Expected FINAL after finalize-pricing, got {final_order['pricing_status']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 53, (
            f"Expected 53 c/lb from the 2026-09-10 quote, got {line['unit_price_cents']}"
        )
        assert line["extended_cents"] == 1028200, (
            f"Expected extended 1028200, got {line['extended_cents']}"
        )
        assert final_order["subtotal_cents"] == 1028200
        assert final_order["fuel_surcharge_cents"] == 25705
        assert final_order["volume_rebate_cents"] == 10282
        assert final_order["total_cents"] == 1043623, (
            f"Expected final total 1043623, got {final_order['total_cents']}"
        )
        assert final_order["total_cents"] != provisional_total, (
            "Delivery-date settlement must differ from the provisional total"
        )


class TestOrderDateIndexSettlement:
    """`ORDER_DATE_INDEX` keeps the order-date observation at settlement."""

    def test_final_settlement_ignores_a_quote_published_after_placement(self):
        """PRD §3.4: "During final settlement, the observation date depends on the
        mode: under `DELIVERY_DATE_INDEX` it is the order's `delivered_on`, and
        under `ORDER_DATE_INDEX` it remains `order_placed_on`."

        Under `ORDER_DATE_INDEX` the 2026-09-10 quote of 47 c/lb is never
        prevailing, so the settled price stays at 38 + 6 = 44 c/lb.

        Design: Difficulty/dual_variant_calc/dual_variant_order_date_index_mode_final_price_ignores_later_quote
        """
        scenario = setup_indexed_contract_delivered_order(
            pricing_mode="ORDER_DATE_INDEX", deliver=True
        )
        assert scenario["provisional_order"]["total_cents"] == 866404

        final_order = validate_success(
            api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC)
        )

        assert final_order["pricing_status"] == "FINAL"
        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 44, (
            f"Expected 44 c/lb at the order-date observation, got {line['unit_price_cents']}"
        )
        assert line["extended_cents"] == 853600
        assert final_order["subtotal_cents"] == 853600
        assert final_order["fuel_surcharge_cents"] == 21340
        assert final_order["volume_rebate_cents"] == 8536
        assert final_order["total_cents"] == 866404, (
            f"Expected final total 866404, got {final_order['total_cents']}"
        )

    def test_delivered_on_is_stamped_with_the_logical_clock_date(self):
        """PRD §3.10: "The order's `delivered_on` is stamped with the logical
        clock date, at which point the order becomes eligible for final pricing."

        The clock is advanced to the route's service date 2026-09-15 before
        dispatch, so the confirmed drop stamps that date.

        Design: Difficulty/dual_variant_calc/dual_variant_order_date_index_mode_final_price_ignores_later_quote
        """
        scenario = setup_indexed_contract_delivered_order(
            pricing_mode="ORDER_DATE_INDEX", deliver=True
        )
        order = read_order(scenario["order"]["id"])
        assert order["fulfillment_status"] == "DELIVERED", (
            f"Expected DELIVERED, got {order['fulfillment_status']}"
        )
        assert order["delivered_on"].startswith("2026-09-15"), (
            f"Expected delivered_on on 2026-09-15, got {order['delivered_on']}"
        )
        assert order["order_placed_on"].startswith("2026-08-05"), (
            f"Expected order_placed_on on 2026-08-05, got {order['order_placed_on']}"
        )

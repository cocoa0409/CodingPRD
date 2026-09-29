"""Provisional versus final observation dates on the same order (PRD §3.4, §3.11)."""

from test_helpers import (
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    create_customer,
    create_product,
    create_route,
    create_zone,
    deliver_stop,
    dispatch_route,
    open_order,
    publish_index_quote,
    read_contract_line,
    read_customer,
    read_order_line,
    receive_lot,
    seal_route,
    set_clock,
    setup_active_contract,
    submit_order,
    validate_success,
)
from test_helpers.fixtures import PC

TERM_START = "2026-08-01T00:00:00Z"
TERM_END = "2026-12-31T00:00:00Z"

HRW_BAG = {
    "sku": "FLR-HRW-BAG",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "HRW_WHEAT",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _delivered_indexed_order(pricing_mode):
    """1000 lb placed 2026-08-10 at the 140 quote and delivered 2026-09-10 after a 200 quote."""
    set_clock(TERM_START)
    customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
    flour = create_product(HRW_BAG)
    publish_index_quote(
        index_code="HRW_WHEAT",
        effective_on="2026-08-01T00:00:00Z",
        price_cents_per_lb=140,
    )
    publish_index_quote(
        index_code="HRW_WHEAT",
        effective_on="2026-09-05T00:00:00Z",
        price_cents_per_lb=200,
    )
    zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
    lot = receive_lot(
        flour["id"],
        zone["id"],
        lot_code="LOT-X-0001",
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=40000,
    )
    active = setup_active_contract(
        customer,
        flour["id"],
        volume_committed_lb=100000,
        basis_cents_per_lb=12,
        pricing_mode=pricing_mode,
        term_start_on=TERM_START,
        term_end_on=TERM_END,
    )
    set_clock("2026-08-10T00:00:00Z")
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on="2026-09-10T00:00:00Z",
        contract_id=active["contract"]["id"],
    )
    line = add_order_line(customer, order["id"], flour["id"], 1000)
    submitted = submit_order(customer, order["id"])
    allocate_order(order["id"])
    route = create_route(
        route_code="R-VAR",
        service_on="2026-09-10T00:00:00Z",
        vehicle_capacity_lb=24000,
        service_buffer_minutes=30,
    )
    stop = append_stop(
        route["id"], order["id"], "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z"
    )
    seal_route(route["id"])
    set_clock("2026-09-10T06:00:00Z")
    dispatch_route(route["id"])
    deliver_stop(stop["id"])
    return {
        "customer": customer,
        "flour": flour,
        "lot": lot,
        "contract": active["contract"],
        "contract_line": active["contract_line"],
        "order": submitted,
        "order_line": line,
    }


class TestDeliveryDateModeReprices:
    """`DELIVERY_DATE_INDEX` swaps the observation date at settlement."""

    def test_finalizing_picks_up_the_quote_published_after_the_order_was_placed(self):
        """PRD §3.4: "During final settlement, the observation date depends on the
        mode: under `DELIVERY_DATE_INDEX` it is the order's `delivered_on`, and under
        `ORDER_DATE_INDEX` it remains `order_placed_on`."

        PRD §3.4: "Consequently, when a contract prices on the delivery date and a
        new quote is published between the order's placement and its delivery, that
        later quote becomes prevailing at final settlement and the final per-pound
        price legitimately differs from the provisional one for identical order
        inputs."

        Design: Corner/calculations/corner_calc_final_variant_repriced_at_delivery_date_quote
        """
        scenario = _delivered_indexed_order("DELIVERY_DATE_INDEX")
        assert scenario["order"]["total_cents"] == 155800, (
            f"Expected the provisional total 155800, got {scenario['order']['total_cents']}"
        )
        assert read_order_line(scenario["order_line"]["id"])["unit_price_cents"] == 152, (
            "The provisional price observes the 2026-08-10 order date"
        )

        final = validate_success(
            api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC)
        )

        assert final["pricing_status"] == "FINAL", (
            f"Expected FINAL, got {final['pricing_status']}"
        )
        assert final["order_placed_on"] == "2026-08-10T00:00:00Z", (
            f"Expected the placement date untouched, got {final['order_placed_on']}"
        )
        assert final["delivered_on"] == "2026-09-10T00:00:00Z", (
            f"Expected the delivery date stamped, got {final['delivered_on']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 212, (
            f"Expected the 200 quote plus the 12 basis, got {line['unit_price_cents']}"
        )
        assert line["extended_cents"] == 212000, (
            f"Expected 1000 lb at 212, got {line['extended_cents']}"
        )
        assert final["subtotal_cents"] == 212000, (
            f"Expected subtotal 212000, got {final['subtotal_cents']}"
        )
        assert final["fuel_surcharge_cents"] == 5300, (
            f"Expected 2.5% of 212000, got {final['fuel_surcharge_cents']}"
        )
        assert final["volume_rebate_cents"] == 0, (
            f"A 217300 rebate base earns nothing, got {final['volume_rebate_cents']}"
        )
        assert final["total_cents"] == 217300, (
            f"Expected total 217300, got {final['total_cents']}"
        )
        assert read_customer(scenario["customer"]["id"])["open_exposure_cents"] == 217300, (
            "The exposure aggregation follows the resettled total"
        )
        assert read_contract_line(scenario["contract_line"]["id"])["volume_drawn_lb"] == 1000, (
            "Finalization reprices but never redraws volume"
        )


class TestOrderDateModeHoldsStill:
    """`ORDER_DATE_INDEX` keeps the placement date even at settlement."""

    def test_finalizing_ignores_a_quote_published_after_the_order_date(self):
        """PRD §3.4: "During final settlement, the observation date depends on the
        mode: under `DELIVERY_DATE_INDEX` it is the order's `delivered_on`, and under
        `ORDER_DATE_INDEX` it remains `order_placed_on`."

        PRD §3.11: "Finalization re-runs the settlement price for every line under
        the delivery-date observation described in §3.4 — producing per-pound prices
        that may legitimately differ from the provisional ones — then re-extends the
        lines, re-runs the order-level waterfall, recomputes the bakery's
        `open_exposure_cents`, and increments the order's `version` by 1."

        The re-run happens all the same; it simply resolves the same 2026-08-01 quote,
        so every figure lands back where it was.

        Design: Corner/calculations/corner_calc_order_date_index_mode_ignores_post_order_quote_at_finalization
        """
        scenario = _delivered_indexed_order("ORDER_DATE_INDEX")

        final = validate_success(
            api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC)
        )

        assert final["pricing_status"] == "FINAL", (
            f"Expected FINAL, got {final['pricing_status']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 152, (
            f"The 2026-09-05 quote is not observed, so expected 152, got {line['unit_price_cents']}"
        )
        assert line["extended_cents"] == 152000, (
            f"Expected 1000 lb at 152, got {line['extended_cents']}"
        )
        assert final["subtotal_cents"] == 152000, (
            f"Expected subtotal 152000, got {final['subtotal_cents']}"
        )
        assert final["fuel_surcharge_cents"] == 3800, (
            f"Expected 2.5% of 152000, got {final['fuel_surcharge_cents']}"
        )
        assert final["total_cents"] == 155800, (
            f"Expected total 155800, got {final['total_cents']}"
        )
        assert read_customer(scenario["customer"]["id"])["open_exposure_cents"] == 155800, (
            "A FINAL order still contributes its total to the exposure ledger"
        )

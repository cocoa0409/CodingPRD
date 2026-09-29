"""Step one of the pricing waterfall: the settled per-pound price (PRD §3.4)."""

from test_helpers import (
    add_order_line,
    create_customer,
    create_product,
    open_order,
    publish_index_quote,
    read_contract,
    read_contract_line,
    read_order,
    read_order_line,
    set_clock,
    setup_active_contract,
    submit_order,
)

TERM_START = "2026-08-01T00:00:00Z"
TERM_END = "2026-12-31T00:00:00Z"

HRW_BULK = {
    "sku": "FLR-HRW-BULK",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "HRW_WHEAT",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
SOFT_OIL_DRUM = {
    "sku": "OIL-SOFT-DRUM",
    "category": "FAT",
    "allergen_class": "SOY",
    "shelf_life_days": 365,
    "index_code": "SOFT_OIL",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
CANE_SUGAR_UNINDEXED = {
    "sku": "SGR-CANE-50",
    "category": "INCLUSION",
    "allergen_class": "NONE",
    "shelf_life_days": 720,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _contracted_line(
    product_spec,
    quotes=(),
    basis_cents_per_lb=12,
    cap_cents_per_lb=None,
    pricing_mode="ORDER_DATE_INDEX",
    order_clock=TERM_START,
    requested_delivery_on="2026-09-05T00:00:00Z",
    quantity_lb=1000,
):
    """An unsubmitted 1000 lb line on an ACTIVE contract, with the quotes published."""
    set_clock(TERM_START)
    customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
    product = create_product(product_spec)
    for effective_on, price_cents_per_lb in quotes:
        publish_index_quote(
            index_code=product_spec["index_code"],
            effective_on=effective_on,
            price_cents_per_lb=price_cents_per_lb,
        )
    active = setup_active_contract(
        customer,
        product["id"],
        volume_committed_lb=100000,
        basis_cents_per_lb=basis_cents_per_lb,
        cap_cents_per_lb=cap_cents_per_lb,
        pricing_mode=pricing_mode,
        term_start_on=TERM_START,
        term_end_on=TERM_END,
    )
    set_clock(order_clock)
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on=requested_delivery_on,
        contract_id=active["contract"]["id"],
    )
    line = add_order_line(customer, order["id"], product["id"], quantity_lb)
    return {
        "customer": customer,
        "product": product,
        "contract": active["contract"],
        "contract_line": active["contract_line"],
        "order": order,
        "order_line": line,
    }


class TestPrevailingQuoteSelection:
    """Greatest `effective_on` on or before the observation date, never the newest row."""

    def test_a_future_quote_and_a_superseded_quote_both_lose_to_the_august_one(self):
        """PRD §3.4: "When the product names a real index, the engine resolves the
        **prevailing quote**: among the published quotes for that index, the one with
        the greatest `effective_on` that is on or before the observation date."

        PRD §3.4: "During submission and during every provisional reprice, the
        observation date is the order's `order_placed_on`, regardless of what the
        contract's `pricing_mode` says."

        Design: Corner/calculations/corner_calc_prevailing_quote_is_latest_effective_on_or_before_order_date
        """
        scenario = _contracted_line(
            HRW_BULK,
            quotes=(
                ("2026-07-01T00:00:00Z", 100),
                ("2026-08-01T00:00:00Z", 140),
                ("2026-09-05T00:00:00Z", 200),
            ),
            basis_cents_per_lb=12,
            cap_cents_per_lb=160,
            order_clock="2026-09-01T00:00:00Z",
            requested_delivery_on="2026-09-20T00:00:00Z",
        )

        submitted = submit_order(scenario["customer"], scenario["order"]["id"])

        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {submitted['pricing_status']}"
        )
        assert submitted["order_placed_on"] == "2026-09-01T00:00:00Z", (
            f"Expected the placement date stamped, got {submitted['order_placed_on']}"
        )
        assert submitted["surge_window"] is False, (
            f"A 2026-09-20 delivery is outside both windows, got {submitted['surge_window']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 152, (
            f"Expected the August quote of 140 plus the 12 basis, got {line['unit_price_cents']}"
        )
        assert line["contract_line_id"] == scenario["contract_line"]["id"], (
            f"Expected the line bound to the commitment line, got {line['contract_line_id']}"
        )
        assert line["extended_cents"] == 152000, (
            f"Expected 1000 lb at 152 with no discount, got {line['extended_cents']}"
        )
        assert submitted["subtotal_cents"] == 152000, (
            f"Expected subtotal 152000, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 3800, (
            f"Expected 2.5% of 152000, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["volume_rebate_cents"] == 0, (
            f"A 155800 rebate base earns nothing, got {submitted['volume_rebate_cents']}"
        )
        assert submitted["total_cents"] == 155800, (
            f"Expected total 155800, got {submitted['total_cents']}"
        )
        assert read_contract_line(scenario["contract_line"]["id"])["volume_drawn_lb"] == 1000, (
            "Submission draws the line's pounds against the commitment"
        )
        assert read_contract(scenario["contract"]["id"])["drawn_volume_lb"] == 1000


class TestCapAndFloorOrdering:
    """Cap then floor, applied to the raw index-plus-basis figure."""

    def test_the_cap_replaces_a_raw_price_that_overshoots_it(self):
        """PRD §3.4: "From the prevailing quote the engine takes
        `price_cents_per_lb`, adds the commitment line's `basis_cents_per_lb`, and
        then applies cap and floor in exactly that order: if the commitment line
        carries a `cap_cents_per_lb` the result becomes the lesser of the two, and if
        the capped result still falls below one cent per pound it is lifted to one
        cent."

        Design: Corner/calculations/corner_calc_cap_binds_on_raw_index_plus_basis
        """
        scenario = _contracted_line(
            HRW_BULK,
            quotes=(("2026-09-05T00:00:00Z", 200),),
            basis_cents_per_lb=12,
            cap_cents_per_lb=160,
            order_clock="2026-09-10T00:00:00Z",
            requested_delivery_on="2026-09-25T00:00:00Z",
        )

        submitted = submit_order(scenario["customer"], scenario["order"]["id"])

        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 160, (
            f"Expected the cap rather than the raw 212, got {line['unit_price_cents']}"
        )
        assert line["contract_line_id"] == scenario["contract_line"]["id"], (
            f"Expected the line bound to the commitment line, got {line['contract_line_id']}"
        )
        assert line["extended_cents"] == 160000, (
            f"Expected 1000 lb at the capped 160, got {line['extended_cents']}"
        )
        assert submitted["subtotal_cents"] == 160000, (
            f"Expected subtotal 160000, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 4000, (
            f"Expected 2.5% of 160000, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["total_cents"] == 164000, (
            f"Expected total 164000, got {submitted['total_cents']}"
        )

    def test_a_negative_basis_is_lifted_to_the_one_cent_floor(self):
        """PRD §3.4: "one cent per pound is the absolute floor on any settled price."

        PRD §3.4: "if the capped result still falls below one cent per pound it is
        lifted to one cent. The outcome is written to `unit_price_cents`."

        The 5-cent quote less the 20-cent basis is a raw negative price, and the
        floor lands it at 1 rather than at the 30-cent catalogue price.

        Design: Corner/calculations/corner_calc_negative_basis_floored_to_min_unit_price
        """
        scenario = _contracted_line(
            SOFT_OIL_DRUM,
            quotes=(("2026-07-15T00:00:00Z", 5),),
            basis_cents_per_lb=-20,
            requested_delivery_on="2026-09-05T00:00:00Z",
        )

        submitted = submit_order(scenario["customer"], scenario["order"]["id"])

        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 1, (
            f"Expected the one-cent floor, got {line['unit_price_cents']}"
        )
        assert line["extended_cents"] == 1000, (
            f"Expected 1000 lb at one cent, got {line['extended_cents']}"
        )
        assert submitted["subtotal_cents"] == 1000, (
            f"Expected subtotal 1000, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 25, (
            f"Expected 2.5% of 1000, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["total_cents"] == 1025, (
            f"Expected total 1025, got {submitted['total_cents']}"
        )
        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {submitted['pricing_status']}"
        )


class TestUnindexedContractBranch:
    """`index_code` of `NONE` returns before any quote or cap is consulted."""

    def test_an_unindexed_sku_prices_at_list_plus_basis_and_ignores_the_cap(self):
        """PRD §3.4: "When the product's `index_code` is `NONE` the SKU has no index
        linkage at all, so the settled price is the product's
        `list_price_cents_per_lb` plus the commitment line's `basis_cents_per_lb`, and
        if that sum falls below one cent per pound it is lifted to one cent — one cent
        per pound is the absolute floor on any settled price."

        PRD §3.4: "If no such quote exists the pricing event is rejected with
        `ERR_INDEX_QUOTE_MISSING` — and that applies to all three pricing events
        alike: submission, a provisional reprice, and final settlement."

        The quote table is empty, yet no `ERR_INDEX_QUOTE_MISSING` can arise: the
        unindexed branch never reaches the resolution step, and the 20-cent cap that
        lives on the same commitment line is never applied either.

        Design: Corner/calculations/corner_calc_none_index_code_returns_list_plus_basis_ignoring_cap
        """
        scenario = _contracted_line(
            CANE_SUGAR_UNINDEXED,
            basis_cents_per_lb=12,
            cap_cents_per_lb=20,
            pricing_mode="DELIVERY_DATE_INDEX",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )

        submitted = submit_order(scenario["customer"], scenario["order"]["id"])

        line = read_order_line(scenario["order_line"]["id"])
        assert line["unit_price_cents"] == 42, (
            f"Expected 30 list plus 12 basis, not the 20 cap or the bare 30, got "
            f"{line['unit_price_cents']}"
        )
        assert line["contract_line_id"] == scenario["contract_line"]["id"], (
            f"Expected the line bound to the commitment line, got {line['contract_line_id']}"
        )
        assert submitted["subtotal_cents"] == 42000, (
            f"Expected subtotal 42000, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 1050, (
            f"Expected 2.5% of 42000, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["total_cents"] == 43050, (
            f"Expected total 43050, got {submitted['total_cents']}"
        )
        assert read_order(scenario["order"]["id"])["pricing_status"] == "PROVISIONAL", (
            "The submission must succeed with no quote in the table at all"
        )

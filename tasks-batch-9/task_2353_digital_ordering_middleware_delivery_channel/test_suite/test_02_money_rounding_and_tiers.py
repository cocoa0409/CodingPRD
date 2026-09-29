"""Where rounding happens, and the order the settlement figures are derived in.

Both families are combinatorial: an order's tax is rounded per line and only then
summed, and a statement's commission rate depends on a tier that is itself chosen
from the same adjusted volume the commission is charged on.
"""
from test_helpers import (
    assert_order,
    assert_order_line,
    assert_order_money_identity,
    assert_remittance_statement,
    assert_statement_pipeline,
    create_aggregator_channel_payload,
    env_partner_headers,
    place_order,
    place_ready_order,
    platter_item_payload,
    read_statement,
    setup_published_store,
    setup_statement_with_orders,
    validate_paginated,
)

AGGREGATOR_ENV = {
    "channel_payloads": [create_aggregator_channel_payload()],
    "item_payloads": [platter_item_payload()],
}


def _lines_by_sku(api, env, order):
    lines, _meta = validate_paginated(
        api.list_order_lines(order["id"], env_partner_headers(env))
    )
    return {line["sku"]: line for line in lines}


def test_order_tax_is_rounded_per_line_and_only_then_summed(api):
    """Two lines round to 221 and 40, so the order's tax is 261 and not 262.

    PRD: "Per line, `line_subtotal_cents` is `unit_price_cents` multiplied by
    `quantity`, and `line_tax_cents` is that line subtotal multiplied by the
    line's `tax_bps`, divided by 10,000, and rounded half up to a whole cent —
    rounded once, per line. The order's `subtotal_cents` is the sum of the line
    subtotals and its `tax_cents` is the sum of the already-rounded line taxes;
    the order tax is never recomputed from the order subtotal, and the two
    figures can genuinely differ."

    Design: Difficulty/combinatorial_formula/nested_rounding_per_line_tax_before_sum
    """
    env = setup_published_store()
    order = place_order(env, external_ref="MP-1001")

    lines = _lines_by_sku(api, env, order)

    for line in lines.values():
        assert_order_line(line)
    assert lines["BURGER"]["unit_price_cents"] == 1265, (
        f"1099 marked up 1500 basis points is 1263.85, rounds to 1264 and lifts to the "
        f"next nickel, got {lines['BURGER']['unit_price_cents']}"
    )
    assert lines["BURGER"]["line_subtotal_cents"] == 2530
    assert lines["BURGER"]["line_tax_cents"] == 221, (
        f"2530 at 875 basis points is 221.375, got {lines['BURGER']['line_tax_cents']}"
    )
    assert lines["FRIES"]["unit_price_cents"] == 460
    assert lines["FRIES"]["line_subtotal_cents"] == 460
    assert lines["FRIES"]["line_tax_cents"] == 40, (
        f"460 at 875 basis points is 40.25, got {lines['FRIES']['line_tax_cents']}"
    )

    assert order["subtotal_cents"] == 2990
    assert order["tax_cents"] == 261, (
        f"221 plus 40, not the 262 that taxing 2990 in one step would give, "
        f"got {order['tax_cents']}"
    )
    assert order["tax_cents"] != 262


def test_order_money_breakdown_satisfies_the_collection_identity(api):
    """Markup, collection, commission and brand net all follow from the snapshot.

    PRD: "`markup_cents` is the order subtotal minus the sum, across lines, of
    each line's `base_price_cents` multiplied by its `quantity` — that is, the
    channel markup the brand's single-source price picked up.
    `channel_collected_cents`, the amount the channel charged the guest, is
    `subtotal_cents` plus `tax_cents` plus `service_fee_cents` plus `tip_cents`.
    `commission_cents` is the sum of `subtotal_cents` and `service_fee_cents`,
    multiplied by the channel's `commission_bps`, divided by 10,000 and rounded
    half up. `brand_net_cents`, the amount owed to the brand, is
    `subtotal_cents` plus `tax_cents` plus `tip_cents` minus `commission_cents`."

    Design: Difficulty/combinatorial_formula/nested_rounding_per_line_tax_before_sum
    """
    env = setup_published_store()
    order = place_order(env, external_ref="MP-1001")

    assert_order(order)
    assert order["markup_cents"] == 393, (
        f"2990 less the single-source 2597, got {order['markup_cents']}"
    )
    assert order["service_fee_cents"] == 299
    assert order["channel_collected_cents"] == 3750, (
        f"2990 plus 261 plus 299 plus a 200 tip, got {order['channel_collected_cents']}"
    )
    assert order["commission_cents"] == 822, (
        f"3289 at 2500 basis points is 822.25, got {order['commission_cents']}"
    )
    assert order["brand_net_cents"] == 2629
    assert_order_money_identity(order)


def test_tier_is_selected_from_the_adjusted_volume_before_commission_is_rated(api):
    """At exactly 50,000 cents the second tier applies and discounts the rate.

    PRD: "Third, the `tier` is selected from that adjusted figure: `TIER_1` when
    `tier_base_cents` is strictly less than 50,000 cents; `TIER_2` when it is at
    or above 50,000 cents and strictly below 200,000 cents; and `TIER_3` at or
    above 200,000 cents. Fourth, an effective commission rate is derived by
    subtracting the tier's volume discount from the channel's `commission_bps`
    and flooring the result at zero, where the discount is 0 basis points at
    `TIER_1`, 50 basis points at `TIER_2`, and 125 basis points at `TIER_3`.
    Fifth, `commission_cents` is `tier_base_cents` multiplied by that effective
    rate, divided by 10,000, and rounded half up."

    Design: Difficulty/combinatorial_formula/circular_tier_base_pins_commission_then_rebate
    """
    env = setup_published_store(**AGGREGATOR_ENV)
    order = place_ready_order(
        env, external_ref="AG-2001", fulfillment_mode="PICKUP",
        lines=[{"sku": "PLATTER", "quantity": 1}], tip_cents=0,
    )

    assert order["subtotal_cents"] == 49851, (
        f"46158 marked up 800 basis points is 49850.64 on a cent grid, "
        f"got {order['subtotal_cents']}"
    )
    assert order["tax_cents"] == 0

    statement = read_statement(setup_statement_with_orders(env, [order])["id"])

    assert_remittance_statement(statement)
    assert statement["gross_sales_cents"] == 50000, (
        f"49851 of sales plus a 149 service fee, got {statement['gross_sales_cents']}"
    )
    assert statement["adjustment_total_cents"] == 0
    assert statement["tier_base_cents"] == 50000
    assert statement["tier"] == "TIER_2", (
        f"50,000 is at the tier boundary and the boundary belongs to the higher tier, "
        f"got {statement['tier']}"
    )
    assert statement["commission_cents"] == 8750, (
        f"1800 basis points less the 50 basis point tier discount, applied to 50000, "
        f"got {statement['commission_cents']}"
    )


def test_rebate_is_rounded_independently_and_a_gross_channel_remits_the_volume(api):
    """The rebate is its own rounding, and gross mode adds it to the volume.

    PRD: "Sixth, `rebate_cents` is `tier_base_cents` multiplied by the tier's
    rebate rate — 0 basis points at `TIER_1`, 25 basis points at `TIER_2`, and 75
    basis points at `TIER_3` — divided by 10,000 and rounded half up
    independently of the commission." "On a `GROSS_MODE` channel the partner
    remits the adjusted volume and the brand is invoiced for commission
    separately, so `net_payable_cents` is `tier_base_cents` plus `rebate_cents`;
    `commission_cents` is still computed and still reported, but it is not
    withheld."

    Design: Difficulty/combinatorial_formula/circular_tier_base_pins_commission_then_rebate
    """
    env = setup_published_store(**AGGREGATOR_ENV)
    order = place_ready_order(
        env, external_ref="AG-2001", fulfillment_mode="PICKUP",
        lines=[{"sku": "PLATTER", "quantity": 1}], tip_cents=0,
    )

    statement = read_statement(setup_statement_with_orders(env, [order])["id"])

    assert statement["rebate_cents"] == 125, (
        f"50000 at the 25 basis point second-tier rebate, got {statement['rebate_cents']}"
    )
    assert statement["net_payable_cents"] == 50125, (
        f"the adjusted volume plus the rebate, with commission invoiced separately, "
        f"got {statement['net_payable_cents']}"
    )
    assert statement["commission_cents"] == 8750, "commission is reported even when not withheld"
    assert_statement_pipeline(statement, commission_bps=1800, settlement_mode="GROSS_MODE")

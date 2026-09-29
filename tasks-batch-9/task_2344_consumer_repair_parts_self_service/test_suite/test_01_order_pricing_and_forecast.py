"""Order pricing arithmetic and the long-tail demand forecast."""
import pytest

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    api_client,
    fixtures,
    get_success_data,
    validate_success,
)


def _read_line(line_id):
    return get_success_data(api_client.get_order_line(line_id, ADMIN))


# --------------------------------------------------------------------------- #
# Two 1005-cent components on a TIER_C model
# --------------------------------------------------------------------------- #
def _two_hinge_order():
    """A consumer draft order holding 3 units of one hinge and 1 unit of another."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-3000",
        product_family="CRX",
        market_release_date="2025-05-01T00:00:00Z",
        repairability_tier="TIER_C_AUTHORIZED_ONLY",
    )
    part_a = fixtures.create_part(sku="SKU-HINGE-A", list_price_cents=1005)
    part_b = fixtures.create_part(sku="SKU-HINGE-B", list_price_cents=1005)
    for part in (part_a, part_b):
        fixtures.create_compatibility(
            part["id"],
            model["id"],
            effective_from="2025-06-01T00:00:00Z",
            install_minutes=20,
        )
        fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-HINGE-A", "SKU-HINGE-B"], safety_warning_count=3
    )
    assessment = fixtures.create_assessment(
        model["id"], part_a["id"], "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    line_a = fixtures.append_line(order["id"], part_a["id"], 3, CUSTOMER)
    line_b = fixtures.append_line(order["id"], part_b["id"], 1, CUSTOMER)
    return {"order": order, "line_a": line_a, "line_b": line_b}


def test_each_line_rounds_once_at_its_own_line_total():
    """PRD §3.6: "The effective unit value is the base multiplied by the buyer
    multiplier, then by the volume multiplier, then by the tier surcharge
    multiplier, and it stays unrounded. `line_total_cents` is then the effective
    unit value multiplied by the line's `quantity`, rounded half up to whole cents
    — and that is the one and only rounding for the line."
    PRD §3.6: "`unit_price_cents` is separately the effective unit value rounded
    half up, and it exists purely for display: it is never multiplied by quantity
    and never summed into any total."

    Design: Difficulty/combinatorial_formula/order_pricing_rounds_each_line_once_before_summing_subtotal
    """
    bundle = _two_hinge_order()
    fixtures.request_disclosure(bundle["order"]["id"], CUSTOMER)

    line_a = _read_line(bundle["line_a"]["id"])
    line_b = _read_line(bundle["line_b"]["id"])

    assert line_a["tier_surcharge_multiplier"] == pytest.approx(1.12, abs=0.01), (
        "a TIER_C_AUTHORIZED_ONLY model carries a 1.12 tier surcharge, got "
        f"{line_a['tier_surcharge_multiplier']}"
    )
    assert line_a["volume_multiplier"] == pytest.approx(1.00, abs=0.01), (
        f"3 units earns no volume discount, got {line_a['volume_multiplier']}"
    )
    assert line_a["line_total_cents"] == 3377, (
        f"Expected 3377 for 3 x 1005 x 1.12 rounded once, got {line_a['line_total_cents']}"
    )
    assert line_a["unit_price_cents"] == 1126, (
        f"Expected the display unit price 1126, got {line_a['unit_price_cents']}"
    )
    assert line_b["line_total_cents"] == 1126, (
        f"Expected 1126 for 1 x 1005 x 1.12, got {line_b['line_total_cents']}"
    )
    assert line_b["unit_price_cents"] == 1126, (
        f"Expected the display unit price 1126, got {line_b['unit_price_cents']}"
    )


def test_parts_subtotal_sums_already_rounded_line_totals():
    """PRD §3.6: "`parts_subtotal_cents` is the sum of `line_total_cents` across
    lines whose part's `part_class` is `COMPONENT` or `CONSUMABLE`."
    PRD §3.6: "Rounding the unit price first and then multiplying, and summing
    unrounded line values and rounding the order total once, are both wrong here."

    Design: Difficulty/combinatorial_formula/order_pricing_rounds_each_line_once_before_summing_subtotal
    """
    bundle = _two_hinge_order()
    order = fixtures.request_disclosure(bundle["order"]["id"], CUSTOMER)

    assert order["parts_subtotal_cents"] == 4503, (
        f"Expected 3377 + 1126 == 4503, got {order['parts_subtotal_cents']}"
    )
    assert order["parts_subtotal_cents"] != 4502, (
        "4502 means the unrounded line values were summed and rounded once"
    )
    assert order["parts_subtotal_cents"] != 4504, (
        "4504 means the unit price was rounded first and then multiplied"
    )
    assert order["documentation_fee_cents"] == 860, (
        f"Expected 500 + 120 x 3 warnings == 860, got {order['documentation_fee_cents']}"
    )
    assert order["total_due_cents"] == 5363, (
        f"Expected 4503 + 860 == 5363, got {order['total_due_cents']}"
    )
    assert order["fulfillment_status"] == "PENDING_DISCLOSURE", (
        f"Expected PENDING_DISCLOSURE after requesting disclosure, got "
        f"{order['fulfillment_status']}"
    )


# --------------------------------------------------------------------------- #
# The 10-unit volume threshold
# --------------------------------------------------------------------------- #
def _ten_unit_order():
    """A consumer draft order holding exactly 10 units of a 1000-cent component."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-9200",
        product_family="CRX",
        market_release_date="2025-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-CLIP-10", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=10
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-CLIP-10"], safety_warning_count=2
    )
    assessment = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    line = fixtures.append_line(order["id"], part["id"], 10, CUSTOMER)
    return {"order": order, "line": line}


def test_volume_discount_applies_at_exactly_ten_units():
    """PRD §3.6: "The line's `volume_multiplier` is 0.85 when `quantity` is at
    least 25, otherwise 0.92 when `quantity` is at least 10, otherwise 1.00; both
    thresholds are inclusive."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_applies_at_exactly_ten_units
    """
    bundle = _ten_unit_order()
    fixtures.request_disclosure(bundle["order"]["id"], CUSTOMER)

    line = _read_line(bundle["line"]["id"])
    assert line["volume_multiplier"] == pytest.approx(0.92, abs=0.01), (
        f"Expected 0.92 at exactly 10 units, got {line['volume_multiplier']}"
    )
    assert line["unit_price_cents"] == 920, (
        f"Expected 1000 x 0.92 == 920, got {line['unit_price_cents']}"
    )
    assert line["line_total_cents"] == 9200, (
        f"Expected 10 x 920 == 9200, got {line['line_total_cents']}"
    )
    assert line["line_total_cents"] != 10000, (
        "10000 means the 10-unit threshold was treated as strictly greater than 10"
    )


def test_ten_unit_order_totals_carry_the_discounted_subtotal():
    """PRD §3.6: "`parts_subtotal_cents` is the sum of `line_total_cents` across
    lines whose part's `part_class` is `COMPONENT` or `CONSUMABLE`."
    PRD §3.6: "otherwise the fee is the smaller of the region's
    `max_documentation_fee_cents` and a computed figure of five dollars — 500 cents
    — plus one dollar twenty — 120 cents — for each liability warning counted in
    the model's published `DISASSEMBLY_GUIDE` revision's `safety_warning_count`."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_applies_at_exactly_ten_units
    """
    bundle = _ten_unit_order()
    order = fixtures.request_disclosure(bundle["order"]["id"], CUSTOMER)

    assert order["parts_subtotal_cents"] == 9200, (
        f"Expected 9200, got {order['parts_subtotal_cents']}"
    )
    assert order["documentation_fee_cents"] == 740, (
        f"Expected 500 + 120 x 2 warnings == 740, got {order['documentation_fee_cents']}"
    )
    assert order["total_due_cents"] == 9940, (
        f"Expected 9200 + 740 == 9940, got {order['total_due_cents']}"
    )


# --------------------------------------------------------------------------- #
# The long-tail demand forecast on a legacy model
# --------------------------------------------------------------------------- #
def _legacy_model_with_delivered_bulk_order():
    """A 27-month-post-EOP model whose only order delivered 216 units."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-4000",
        product_family="CRX",
        market_release_date="2022-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
        end_of_production_date="2024-06-01T00:00:00Z",
    )
    part = fixtures.create_part(sku="SKU-FAN-LT", list_price_cents=1200)
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2022-02-01T00:00:00Z", install_minutes=15
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(model["id"], ["SKU-FAN-LT"], safety_warning_count=3)

    assessment = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    line = fixtures.append_line(order["id"], part["id"], 216, CUSTOMER)
    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    fixtures.confirm_order(order["id"], CUSTOMER)
    fixtures.deliver_order(order["id"])
    fixtures.move_clock("2026-09-01T00:00:00Z")
    return {"model": model, "part": part, "order": order, "line": line}


def _forecast(part_id, model_id, horizon_months, variant="TRAILING_ONLY"):
    response = api_client.get_demand_forecast(
        part_id,
        COMPLIANCE,
        params={
            "model_id": model_id,
            "horizon_months": horizon_months,
            "variant": variant,
        },
    )
    return validate_success(response, 200)


def test_bulk_delivered_line_prices_at_the_twenty_five_unit_discount():
    """PRD §3.6: "The line's `volume_multiplier` is 0.85 when `quantity` is at
    least 25, otherwise 0.92 when `quantity` is at least 10, otherwise 1.00; both
    thresholds are inclusive."

    Design: Difficulty/combinatorial_formula/demand_forecast_pins_safety_stock_tier_to_prepad_projection
    """
    bundle = _legacy_model_with_delivered_bulk_order()

    line = _read_line(bundle["line"]["id"])
    assert line["volume_multiplier"] == pytest.approx(0.85, abs=0.01), (
        f"Expected 0.85 at 216 units, got {line['volume_multiplier']}"
    )
    assert line["line_total_cents"] == 220320, (
        f"Expected 216 x 1200 x 0.85 == 220320, got {line['line_total_cents']}"
    )


def test_forecast_bands_a_legacy_model_off_its_trailing_window():
    """PRD §3.9: "First, `trailing_units` is the sum of `quantity` over every line
    for this part whose order is on the given model, whose order's
    `fulfillment_status` is `DELIVERED` or `CLOSED`, and whose order's
    `confirmed_at` falls within the half-open interval that starts 180 days before
    the logical clock and ends at, but excludes, the logical clock itself."
    PRD §3.9: "the `obsolescence_band` is `CURRENT` when that count is below 12,
    `LEGACY` when it is at least 12 and at most 60, and `LONG_TAIL` when it exceeds
    60; the corresponding `band_multiplier` is 1.00, 1.35, and 1.80."

    Design: Difficulty/combinatorial_formula/demand_forecast_pins_safety_stock_tier_to_prepad_projection
    """
    bundle = _legacy_model_with_delivered_bulk_order()
    forecast = _forecast(bundle["part"]["id"], bundle["model"]["id"], 10)

    assert forecast["variant"] == "TRAILING_ONLY", forecast["variant"]
    assert forecast["trailing_units"] == 216, (
        f"Expected the delivered 216 units, got {forecast['trailing_units']}"
    )
    assert forecast["pipeline_units"] == 0, (
        f"A delivered order contributes nothing to pipeline_units, got "
        f"{forecast['pipeline_units']}"
    )
    assert forecast["base_monthly_units"] == pytest.approx(36.0, abs=0.01), (
        f"Expected 216 / 6 == 36.0, got {forecast['base_monthly_units']}"
    )
    assert forecast["obsolescence_band"] == "LEGACY", forecast["obsolescence_band"]
    assert forecast["band_multiplier"] == pytest.approx(1.35, abs=0.01), (
        f"Expected 1.35 for LEGACY, got {forecast['band_multiplier']}"
    )
    assert forecast["projected_units"] == pytest.approx(486.0, abs=0.01), (
        f"Expected 36.0 x 10 x 1.35 == 486.0, got {forecast['projected_units']}"
    )


def test_forecast_reads_the_safety_stock_tier_from_the_unpadded_projection():
    """PRD §3.9: "Seventh, `safety_stock_pct` is read from that step-six value:
    0.30 when `projected_units` is below 50, otherwise 0.20 when it is below 500,
    otherwise 0.12."
    PRD §3.9: "Ninth, `recommended_stock_units` is `projected_units` multiplied by
    one plus `safety_stock_pct`, rounded up to a whole unit, plus
    `mandated_buffer_units`."

    Design: Difficulty/combinatorial_formula/demand_forecast_pins_safety_stock_tier_to_prepad_projection
    """
    bundle = _legacy_model_with_delivered_bulk_order()
    forecast = _forecast(bundle["part"]["id"], bundle["model"]["id"], 10)

    assert forecast["safety_stock_pct"] == pytest.approx(0.20, abs=0.01), (
        "the tier is read from the unpadded 486.0 projection, got "
        f"{forecast['safety_stock_pct']}"
    )
    assert forecast["mandated_buffer_units"] == 0, (
        "no compliance obligation exists for the model, got "
        f"{forecast['mandated_buffer_units']}"
    )
    assert forecast["recommended_stock_units"] == 584, (
        f"Expected ceil(486.0 x 1.20) == 584, got {forecast['recommended_stock_units']}"
    )
    assert forecast["recommended_stock_units"] != 545, (
        "545 means the safety-stock tier was re-read from the padded figure"
    )


# --------------------------------------------------------------------------- #
# The long-tail demand forecast with nothing to aggregate
# --------------------------------------------------------------------------- #
def _model_with_no_orders():
    """A current-band model and a published part that nobody has ever ordered."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-9100",
        product_family="CRX",
        market_release_date="2026-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-QUIET-1", list_price_cents=1500)
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2026-02-01T00:00:00Z", install_minutes=15
    )
    fixtures.publish_part(part["id"])
    return {"model": model, "part": part}


def test_empty_trailing_window_reports_zero_aggregates():
    """PRD §3.9: "Third, `base_monthly_units` is `trailing_units` divided by six,
    the trailing window being six months long, and is left unrounded."
    PRD §3.9: "Second, `pipeline_units` is the sum of `quantity` over the same join
    where the order's `fulfillment_status` is `PENDING_DISCLOSURE` or `CONFIRMED`,
    with no date filter at all."

    Design: Difficulty/boundary_precision_check/demand_forecast_empty_trailing_window_yields_zero_recommended_stock
    """
    bundle = _model_with_no_orders()
    response = api_client.get_demand_forecast(
        bundle["part"]["id"],
        ADMIN,
        params={
            "model_id": bundle["model"]["id"],
            "horizon_months": 12,
            "variant": "TRAILING_ONLY",
        },
    )
    forecast = validate_success(response, 200)

    assert forecast["trailing_units"] == 0, forecast["trailing_units"]
    assert forecast["pipeline_units"] == 0, forecast["pipeline_units"]
    assert forecast["base_monthly_units"] == pytest.approx(0.0, abs=0.01), (
        f"Expected 0 / 6 == 0.0, got {forecast['base_monthly_units']}"
    )
    assert forecast["obsolescence_band"] == "CURRENT", forecast["obsolescence_band"]
    assert forecast["band_multiplier"] == pytest.approx(1.00, abs=0.01), (
        f"Expected 1.00 for CURRENT, got {forecast['band_multiplier']}"
    )


def test_empty_trailing_window_still_tiers_at_thirty_percent_and_recommends_zero():
    """PRD §3.9: "Seventh, `safety_stock_pct` is read from that step-six value:
    0.30 when `projected_units` is below 50, otherwise 0.20 when it is below 500,
    otherwise 0.12."
    PRD §3.9: "the mandated months remaining are the whole months from the logical
    clock to the latest `parts_available_until` across this model's compliance
    obligations whose `status` is not `CLOSED`, taken as zero when there is no such
    obligation or when that deadline already lies in the past."

    Design: Difficulty/boundary_precision_check/demand_forecast_empty_trailing_window_yields_zero_recommended_stock
    """
    bundle = _model_with_no_orders()
    response = api_client.get_demand_forecast(
        bundle["part"]["id"],
        ADMIN,
        params={
            "model_id": bundle["model"]["id"],
            "horizon_months": 12,
            "variant": "TRAILING_ONLY",
        },
    )
    forecast = validate_success(response, 200)

    assert forecast["projected_units"] == pytest.approx(0.0, abs=0.01), (
        f"Expected 0.0, got {forecast['projected_units']}"
    )
    assert forecast["safety_stock_pct"] == pytest.approx(0.30, abs=0.01), (
        f"Expected the below-50 tier 0.30, got {forecast['safety_stock_pct']}"
    )
    assert forecast["mandated_buffer_units"] == 0, forecast["mandated_buffer_units"]
    assert forecast["recommended_stock_units"] == 0, (
        f"Expected exactly 0 with no unit floor, got {forecast['recommended_stock_units']}"
    )

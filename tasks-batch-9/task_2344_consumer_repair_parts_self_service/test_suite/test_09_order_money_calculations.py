"""Order money: the documentation fee, the single per-line rounding, the five
disjoint order-level buckets, and the occupancy filter behind a rental deposit.
"""
import pytest

from test_helpers import (
    ADMIN,
    CUSTOMER,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)


def _publish_part_on(model_id, sku, **part_overrides):
    """One published part with an in-window compatibility row on the given model."""
    part = fixtures.create_part(sku=sku, **part_overrides)
    fixtures.create_compatibility(
        part["id"], model_id, effective_from="2024-02-01T00:00:00Z", install_minutes=20
    )
    return fixtures.publish_part(part["id"])


def test_documentation_fee_takes_the_cap_in_one_region_and_zero_in_the_other():
    """PRD §3.6: "Then `documentation_fee_cents`: when the region's
    `requires_public_manual` is true the fee is zero, because the statutory
    free-documentation override wins before anything else is considered; otherwise the
    fee is the smaller of the region's `max_documentation_fee_cents` and a computed
    figure of five dollars — 500 cents — plus one dollar twenty — 120 cents — for each
    liability warning counted in the model's published `DISASSEMBLY_GUIDE` revision's
    `safety_warning_count`."
    PRD §3.6: "Finally `total_due_cents` is the sum of `parts_subtotal_cents`,
    `tool_purchase_cents`, `rental_deposit_cents`, `documentation_fee_cents`, and
    `core_deposit_cents`."

    Design: Corner/calculations/documentation_fee_takes_the_regional_cap_and_the_public_manual_override
    """
    fixtures.create_region(
        region_code="US-NY", max_documentation_fee_cents=600, requires_public_manual=False
    )
    fixtures.create_region(
        region_code="EU-FR", max_documentation_fee_cents=600, requires_public_manual=True
    )
    model = fixtures.create_model(
        model_code="CRX-C201",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = _publish_part_on(model["id"], "SKU-C201-FAN", list_price_cents=1000)
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-C201-FAN"], safety_warning_count=5
    )

    priced = {}
    for region_code in ("US-NY", "EU-FR"):
        assessment = fixtures.create_assessment(
            model["id"], part["id"], region_code, CUSTOMER
        )
        order = fixtures.create_order(assessment["id"], region_code, CUSTOMER)
        fixtures.append_line(order["id"], part["id"], 1, CUSTOMER)
        priced[region_code] = fixtures.request_disclosure(order["id"], CUSTOMER)

    new_york = priced["US-NY"]
    assert new_york["documentation_fee_cents"] == 600, (
        f"Expected the 600 cap to bite on an uncapped 1100, got "
        f"{new_york['documentation_fee_cents']}"
    )
    assert new_york["total_due_cents"] == 1600, (
        f"Expected the 1000 subtotal plus the 600 fee, got "
        f"{new_york['total_due_cents']}"
    )

    france = priced["EU-FR"]
    assert france["documentation_fee_cents"] == 0, (
        f"a jurisdiction demanding free documentation charges nothing, got "
        f"{france['documentation_fee_cents']}"
    )
    assert france["total_due_cents"] == 1000, (
        f"Expected the subtotal alone, got {france['total_due_cents']}"
    )

    for region_code, order in priced.items():
        assert order["parts_subtotal_cents"] == 1000, (
            f"{region_code} prices the same single component line, got "
            f"{order['parts_subtotal_cents']}"
        )
        assert order["core_deposit_cents"] == 0, order["core_deposit_cents"]
        assert order["rental_deposit_cents"] == 0, order["rental_deposit_cents"]
        assert order["tool_purchase_cents"] == 0, order["tool_purchase_cents"]


def test_the_tier_surcharge_multiplies_the_unit_before_the_only_line_rounding():
    """PRD §3.6: "The effective unit value is the base multiplied by the buyer
    multiplier, then by the volume multiplier, then by the tier surcharge multiplier,
    and it stays unrounded."
    PRD §3.6: "`unit_price_cents` is separately the effective unit value rounded half
    up, and it exists purely for display: it is never multiplied by quantity and never
    summed into any total."

    Design: Corner/calculations/tier_b_surcharge_lands_on_the_unit_before_the_single_line_rounding
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-C203",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_B_GUIDED",
        },
        part_overrides={"sku": "SKU-C203-BRD", "list_price_cents": 993},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "self_service_eligible": True,
            "install_minutes": 30,
        },
        safety_warning_count=2,
    )
    assessment = fixtures.create_assessment(
        setup["model"]["id"], setup["part"]["id"], "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)

    response = api_client.append_order_line(
        order["id"],
        factories.order_line_payload(
            setup["part"]["id"], fixtures.order_version(order["id"], CUSTOMER), 3
        ),
        CUSTOMER,
    )
    line = validate_success(response, 201)

    assert line["line_total_cents"] == 3128, (
        f"Expected 993 times 1.05 times three rounded once, got "
        f"{line['line_total_cents']}"
    )
    assert line["unit_price_cents"] == 1043, (
        f"Expected the display unit rounded from 1042.65, got "
        f"{line['unit_price_cents']}"
    )
    assert line["unit_price_cents"] * 3 != line["line_total_cents"], (
        "rounding the unit first and then multiplying would give 3129, which is the "
        "wrong total"
    )
    assert line["volume_multiplier"] == pytest.approx(1.00, abs=0.01), (
        f"three units is below the ten-unit tier, got {line['volume_multiplier']}"
    )
    assert line["tier_surcharge_multiplier"] == pytest.approx(1.05, abs=0.01), (
        f"Expected the guided-tier surcharge, got {line['tier_surcharge_multiplier']}"
    )

    priced = fixtures.request_disclosure(order["id"], CUSTOMER)
    assert priced["parts_subtotal_cents"] == 3128, priced["parts_subtotal_cents"]
    assert priced["total_due_cents"] == 3868, (
        f"Expected the 3128 subtotal plus the 740 fee, got {priced['total_due_cents']}"
    )
    assert priced["warranty_impact_class"] == "WARRANTY_VOID_AFFECTED_SUBSYSTEM", (
        f"the preserved-with-log branch needs a self-service tier, got "
        f"{priced['warranty_impact_class']}"
    )


def test_tools_rentals_and_cores_land_in_their_own_buckets():
    """PRD §3.6: "`parts_subtotal_cents` is the sum of `line_total_cents` across lines
    whose part's `part_class` is `COMPONENT` or `CONSUMABLE`."
    PRD §3.6: "`core_deposit_cents` is the sum, across lines whose part has
    `core_return_required` true, of that part's `core_credit_cents` multiplied by the
    line's `quantity`."

    Design: Corner/calculations/tool_rental_and_core_buckets_stay_out_of_the_parts_subtotal
    """
    fixtures.create_region(region_code="US-CA", max_documentation_fee_cents=2000)
    model = fixtures.create_model(
        model_code="CRX-C204",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    component = _publish_part_on(
        model["id"],
        "SKU-C204-MOD",
        list_price_cents=1000,
        core_return_required=True,
        core_credit_cents=900,
    )
    tool = _publish_part_on(
        model["id"], "SKU-C204-TOOL", part_class="TOOL", list_price_cents=500
    )
    kit = _publish_part_on(
        model["id"],
        "SKU-C204-KIT",
        part_class="RENTAL_KIT",
        list_price_cents=0,
        rental_deposit_cents=5000,
        concurrent_rental_capacity=2,
    )
    fixtures.publish_disassembly_guide(
        model["id"],
        ["SKU-C204-MOD", "SKU-C204-TOOL", "SKU-C204-KIT"],
        safety_warning_count=2,
    )

    assessment = fixtures.create_assessment(
        model["id"], component["id"], "US-CA", CUSTOMER
    )
    order = fixtures.create_order(
        assessment["id"],
        "US-CA",
        CUSTOMER,
        rental_window_start="2026-08-05T00:00:00Z",
        rental_window_end="2026-08-07T00:00:00Z",
    )
    component_line = fixtures.append_line(order["id"], component["id"], 2, CUSTOMER)
    fixtures.append_line(order["id"], tool["id"], 1, CUSTOMER)
    kit_line = fixtures.append_line(order["id"], kit["id"], 1, CUSTOMER)

    priced = fixtures.request_disclosure(order["id"], CUSTOMER)
    assert priced["parts_subtotal_cents"] == 2000, (
        f"only the component line reaches the parts subtotal, got "
        f"{priced['parts_subtotal_cents']}"
    )
    assert priced["tool_purchase_cents"] == 500, priced["tool_purchase_cents"]
    assert priced["rental_deposit_cents"] == 5000, (
        f"the deposit comes from the catalog row, not the kit's line total, got "
        f"{priced['rental_deposit_cents']}"
    )
    assert priced["core_deposit_cents"] == 1800, (
        f"Expected 900 face value times two units with no multiplier, got "
        f"{priced['core_deposit_cents']}"
    )
    assert priced["documentation_fee_cents"] == 740, priced["documentation_fee_cents"]
    assert priced["total_due_cents"] == 10040, (
        f"Expected the five buckets summed, got {priced['total_due_cents']}"
    )

    lines = {line["id"]: line for line in fixtures.list_lines(order["id"])}
    assert lines[kit_line["id"]]["line_total_cents"] == 0, (
        f"the kit's money is a deposit, not a line price, got "
        f"{lines[kit_line['id']]['line_total_cents']}"
    )
    assert lines[component_line["id"]]["line_total_cents"] == 2000, (
        lines[component_line["id"]]["line_total_cents"]
    )
    assert lines[component_line["id"]]["unit_price_cents"] == 1000, (
        lines[component_line["id"]]["unit_price_cents"]
    )


def test_a_cancelled_order_releases_the_rental_kit_it_was_holding():
    """PRD §3.6: "Every line on the same part belonging to a *different* order whose
    `fulfillment_status` is `PENDING_DISCLOSURE`, `CONFIRMED`, or `DELIVERED` counts as
    an occupant; occupations on orders in `DRAFT`, `BLOCKED_SAFETY_HOLD`, `CLOSED`, or
    `CANCELLED` are released and never counted."
    PRD §3.6: "The pinned assessment stays `CONSUMED` — a cancellation never
    resurrects eligibility."

    Design: Corner/calculations/cancelled_rental_occupation_releases_the_kit_capacity
    """
    fixtures.create_region(region_code="US-CA", max_documentation_fee_cents=2000)
    model = fixtures.create_model(
        model_code="CRX-C213",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    kit = _publish_part_on(
        model["id"],
        "SKU-C213-KIT",
        part_class="RENTAL_KIT",
        list_price_cents=0,
        rental_deposit_cents=5000,
        concurrent_rental_capacity=1,
    )
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-C213-KIT"], safety_warning_count=2
    )

    assessment_a = fixtures.create_assessment(model["id"], kit["id"], "US-CA", CUSTOMER)
    order_a = fixtures.create_order(
        assessment_a["id"],
        "US-CA",
        CUSTOMER,
        rental_window_start="2026-08-05T00:00:00Z",
        rental_window_end="2026-08-07T00:00:00Z",
    )
    fixtures.append_line(order_a["id"], kit["id"], 1, CUSTOMER)
    fixtures.request_disclosure(order_a["id"], CUSTOMER)
    cancelled = fixtures.cancel_order(
        order_a["id"], CUSTOMER, cancellation_reason="repair no longer needed"
    )
    assert cancelled["fulfillment_status"] == "CANCELLED", (
        cancelled["fulfillment_status"]
    )

    assessment_b = fixtures.create_assessment(model["id"], kit["id"], "US-CA", CUSTOMER)
    order_b = fixtures.create_order(
        assessment_b["id"],
        "US-CA",
        CUSTOMER,
        rental_window_start="2026-08-06T00:00:00Z",
        rental_window_end="2026-08-08T00:00:00Z",
    )
    response = api_client.append_order_line(
        order_b["id"],
        factories.order_line_payload(
            kit["id"], fixtures.order_version(order_b["id"], CUSTOMER), 1
        ),
        CUSTOMER,
    )
    line_b = validate_success(response, 201)
    assert line_b["line_total_cents"] == 0, line_b["line_total_cents"]

    priced_b = fixtures.request_disclosure(order_b["id"], CUSTOMER)
    assert priced_b["rental_deposit_cents"] == 5000, (
        f"the released kit is charged to the new occupant, got "
        f"{priced_b['rental_deposit_cents']}"
    )

    consumed = get_success_data(
        api_client.get_eligibility_assessment(assessment_a["id"], ADMIN)
    )
    assert consumed["status"] == "CONSUMED", (
        f"the cancellation must not resurrect the ruling, got {consumed['status']}"
    )

"""Actuator packaging and torque sizing.

The sizing ladder is built up from the design and the service in a fixed order, and
two things about it are load-bearing: which base the ``sizing_basis`` selects, and
that the safety-margin tier is keyed on the already-rounded required torque.
"""

from test_helpers import (
    SizingStatus,
    assert_created,
    assert_torque,
    assert_torque_envelope,
    factories,
    fixtures,
    make_product_engineer_headers,
)

BALL_300_METAL = dict(
    foundry_code="FDY-01",
    foundry_name="Alpha Castings",
    country_code="IN",
    process="CASTING",
    material_grade="CF8M",
    max_pressure_class=600,
    heat_number="H-1001",
    mtr_document_ref="MTR-1001",
    model_code="BV-300-CF8M",
    valve_type="BALL",
    pressure_class=300,
    bore_size_mm=100,
    seat_type="METAL",
    base_break_torque_nm=420.0,
    license_code="MON-01",
    scope_valve_types=["BALL", "GATE"],
)


def _two_unit_line(api):
    """A released quarter-turn metal-seated class-300 design with two body components:
    unit SN-A stands alone, unit SN-B belongs to an order stating 420.0 Nm CUSTOMER_STATED."""
    line = fixtures.build_traceable_line(api, **BALL_300_METAL)
    second_component = fixtures.draw_component(
        api, line["lot"]["id"], line["model"]["id"], net_weight_kg=120.500
    )
    unit_a = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-A",
    )
    order = fixtures.create_order(
        api,
        line["model"]["id"],
        order_code="ETO-1",
        ordered_qty=1,
        unit_price_cents=1_000_000,
        customer_credit_limit_cents=5_000_000,
        datasheet_break_torque_nm=420.0,
        datasheet_torque_source="CUSTOMER_STATED",
    )
    unit_b = fixtures.open_unit(
        api,
        line["model"]["id"],
        second_component["id"],
        line["license"]["id"],
        serial_number="SN-B",
        engineered_order_id=order["id"],
    )
    return {"line": line, "unit_a": unit_a, "unit_b": unit_b, "order": order}


def _propose(api, unit, sizing_basis, output_torque_nm=900.0, actuator_type="PNEUMATIC"):
    payload = factories.actuator_package_payload(
        unit["id"],
        actuator_type,
        output_torque_nm,
        sizing_basis,
        unit["version"],
        supply_pressure_bar=5.5 if actuator_type != "ELECTRIC" else None,
    )
    return api.create_actuator_package(payload, make_product_engineer_headers())


def test_01_catalog_basis_sizes_from_the_design_catalog_break_torque(api):
    """With CATALOG the base is the design's own catalog break torque and no
    uncertainty allowance is added.

    PRD §3.5: "with `CATALOG`, the base is the design's `base_break_torque_nm` and no
    uncertainty allowance is added". A quarter-turn class-300 metal-seated body with a 420.0
    catalog break torque sizes to 703.0 newton-metres from the catalog.

    Design: Difficulty/dual_variant_calc/actuator_sizing_catalog_variant_vs_datasheet_variant
    """
    scenario = _two_unit_line(api)

    package = assert_created(_propose(api, scenario["unit_a"], "CATALOG"))

    assert_torque_envelope(
        package, required_torque_nm=562.4, safety_margin_pct=0.25, sized_torque_nm=703.0
    )
    assert package["sizing_status"] == SizingStatus.PROPOSED
    assert package["sizing_basis"] == "CATALOG"


def test_02_datasheet_basis_adds_the_customer_stated_uncertainty_allowance(api):
    """With DATASHEET the base is the order's datasheet torque, inflated because the
    customer stated it.

    PRD §3.5: "with `DATASHEET`, which is selected when the unit belongs to an engineered
    order carrying a customer datasheet, the base is that order's
    `datasheet_break_torque_nm` multiplied by 1.10 when its `datasheet_torque_source` is
    `CUSTOMER_STATED`, or by 1.00 when the source is `VENDOR_MEASURED` — a customer's stated
    figure earns a ten per cent uncertainty allowance that a vendor-measured figure does
    not." The same 420.0 therefore sizes to 773.3.

    Design: Difficulty/dual_variant_calc/actuator_sizing_catalog_variant_vs_datasheet_variant
    """
    scenario = _two_unit_line(api)

    package = assert_created(_propose(api, scenario["unit_b"], "DATASHEET"))

    assert_torque_envelope(
        package, required_torque_nm=618.6, safety_margin_pct=0.25, sized_torque_nm=773.3
    )
    assert package["sizing_status"] == SizingStatus.PROPOSED
    assert package["sizing_basis"] == "DATASHEET"


def test_03_the_two_bases_diverge_on_the_same_design_and_the_same_margin_tier(api):
    """The two bases give different answers for the same model and the same torque figure.

    PRD §3.5: "Because the same unit and design can produce different answers under the
    two bases, `sizing_basis` is a load-bearing input, not a label: a quarter-turn class-300
    metal-seated body with a 420.0 catalog break torque sizes to 703.0 newton-metres from
    the catalog and to 773.3 from a customer-stated datasheet of the same 420.0."

    Design: Difficulty/dual_variant_calc/actuator_sizing_catalog_variant_vs_datasheet_variant
    """
    scenario = _two_unit_line(api)

    catalog = assert_created(_propose(api, scenario["unit_a"], "CATALOG"))
    datasheet = assert_created(_propose(api, scenario["unit_b"], "DATASHEET"))

    assert_torque(catalog["required_torque_nm"], 562.4, "catalog required_torque_nm")
    assert_torque(datasheet["required_torque_nm"], 618.6, "datasheet required_torque_nm")
    assert_torque(
        float(datasheet["required_torque_nm"]) - float(catalog["required_torque_nm"]),
        56.2,
        "divergence between the two bases",
    )
    # Both land in the same tier, so the divergence is the base and not the margin.
    assert float(catalog["safety_margin_pct"]) == float(datasheet["safety_margin_pct"]) == 0.25
    assert catalog["sizing_status"] == SizingStatus.PROPOSED
    assert datasheet["sizing_status"] == SizingStatus.PROPOSED


def _edge_line(api):
    """A soft-seated quarter-turn class-300 design whose 485.4 base lands the unrounded
    requirement at 499.962 — one hundredth short of the tier edge before rounding."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-04",
        foundry_name="Delta Castings",
        country_code="IN",
        process="CASTING",
        material_grade="CF8M",
        max_pressure_class=600,
        heat_number="H-4001",
        mtr_document_ref="MTR-4001",
        model_code="BV-300-EDGE",
        valve_type="BALL",
        pressure_class=300,
        bore_size_mm=100,
        seat_type="SOFT",
        base_break_torque_nm=485.4,
        release_design=False,
        license_code="MON-04",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    fixtures.submit_model_for_review(api, line["model"]["id"])
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-EDGE",
    )
    return {"line": line, "unit": unit}


def test_04_margin_tier_is_selected_from_the_already_rounded_required_torque(api):
    """485.4 times the 1.03 pressure factor is 499.962, which rounds to 500.0 and takes
    the tier that begins at 500.

    PRD §3.5: "below 500 newton-metres the margin is 0.30, from 500 up to and including 2000
    it is 0.25, and above 2000 it is 0.20. This matters at the boundary — an unrounded
    requirement of 499.96 rounds to 500.0 and therefore takes the 0.25 tier rather than the
    0.30 tier."

    Design: Difficulty/combinatorial_formula/actuator_margin_tier_keyed_on_rounded_required_torque
    """
    scenario = _edge_line(api)

    package = assert_created(
        _propose(api, scenario["unit"], "CATALOG", output_torque_nm=700.0, actuator_type="ELECTRIC")
    )

    assert_torque(package["required_torque_nm"], 500.0, "required_torque_nm")
    assert float(package["safety_margin_pct"]) == 0.25, (
        "A required torque of exactly 500.0 takes the 500-to-2000 tier, not the below-500 tier"
    )


def test_05_sized_torque_follows_the_rounded_tier_rather_than_the_unrounded_product(api):
    """The sized torque is the required torque multiplied by one plus the tier margin.

    PRD §3.5: "The tier is stored in `safety_margin_pct` as a fraction to 2 decimal places,
    and `sized_torque_nm` is `required_torque_nm` multiplied by one plus that margin, again
    rounded half up to 1 decimal place." At the 0.25 tier 500.0 sizes to 625.0; the
    below-500 tier would have given 650.0.

    Design: Difficulty/combinatorial_formula/actuator_margin_tier_keyed_on_rounded_required_torque
    """
    scenario = _edge_line(api)

    package = assert_created(
        _propose(api, scenario["unit"], "CATALOG", output_torque_nm=700.0, actuator_type="ELECTRIC")
    )

    assert_torque(package["sized_torque_nm"], 625.0, "sized_torque_nm")
    assert float(package["sized_torque_nm"]) != 650.0, (
        "650.0 would mean the tier had been keyed on the unrounded 499.962"
    )

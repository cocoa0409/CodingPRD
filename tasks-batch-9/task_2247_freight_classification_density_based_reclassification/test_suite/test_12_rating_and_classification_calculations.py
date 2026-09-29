"""The rating arithmetic: cube, density, the weight break, the floor and the delta.

Every figure here is engineered so that a plausible shortcut lands somewhere
else — a single rounding over the whole volume, a per-line weight break, a
per-line minimum charge, or a measured weight that was never captured.
"""

from test_helpers import assert_correction_notice, assert_rate_program
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"

DRUM_LINE = {
    "line_no": 1,
    "declared_class_code": 60,
    "declared_weight_lb": 3055,
    "pieces": 22,
    "declared_length_in": 20.0,
    "declared_width_in": 20.0,
    "declared_height_in": 20.0,
}

FOUR_HUNDRED_POUND_LINE = {
    "line_no": 1,
    "declared_class_code": 70,
    "declared_weight_lb": 400,
    "pieces": 4,
    "declared_length_in": 48.0,
    "declared_width_in": 40.0,
    "declared_height_in": 48.0,
}

BOXED_LINE = {
    "line_no": 2,
    "declared_class_code": 70,
    "declared_weight_lb": 400,
    "pieces": 4,
    "declared_length_in": 48.0,
    "declared_width_in": 40.0,
    "declared_height_in": 48.0,
}

SEVEN_HUNDRED_POUND_LINE = {
    "line_no": 2,
    "declared_class_code": 100,
    "declared_weight_lb": 700,
    "pieces": 2,
    "declared_length_in": 40.0,
    "declared_width_in": 40.0,
    "declared_height_in": 40.0,
}

SIX_HUNDRED_POUND_LINE = {
    "line_no": 1,
    "declared_class_code": 70,
    "declared_weight_lb": 600,
    "pieces": 1,
    "declared_length_in": 48.0,
    "declared_width_in": 40.0,
    "declared_height_in": 40.0,
}


# ==========================================================================
# Cube, density and the charge floor
# ==========================================================================


def test_cube_rounds_per_handling_unit_before_the_pieces_are_multiplied():
    """Twenty-two 20-inch cubes come to 101.86, not the 101.85 a single rounding gives.

    PRD: "The volume of one handling unit is length multiplied by width multiplied
    by height, divided by 1,728 cubic inches per cubic foot, and rounded to three
    decimal places. That per-unit figure is then multiplied by the piece count and
    rounded to two decimal places, which gives `declared_cubic_ft`."

    Design: Corner/calculations/cube_and_density_two_step_rounding_precision
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.setup_shipment_with_lines(
        env,
        "PROC001",
        line_specs=[DRUM_LINE, BOXED_LINE],
        bol_declared_total_weight_lb=3455,
    )

    drums = fx.get_shipment_line(tendered["line_ids"][0])
    boxes = fx.get_shipment_line(tendered["line_ids"][1])
    shipment = fx.get_shipment(tendered["shipment_id"])

    assert drums["declared_cubic_ft"] == 101.86, (
        f"4.630 cubic feet per unit times 22 units is 101.86, not 101.85, "
        f"got {drums['declared_cubic_ft']}"
    )
    assert drums["declared_density_pcf"] == 29.99, (
        f"3055 pounds over 101.86 cubic feet is 29.99, not 30.00, "
        f"got {drums['declared_density_pcf']}"
    )
    assert boxes["declared_cubic_ft"] == 213.33
    assert boxes["declared_density_pcf"] == 1.88
    assert shipment["declared_total_weight_lb"] == 3455
    assert shipment["line_count"] == 2
    assert shipment["billing_status"] == "UNBILLED"


def test_the_minimum_charge_floors_the_shipment_but_not_the_line():
    """The 9937-cent computed freight is floored at 12500 only at shipment level.

    PRD: "Those raw amounts are added across all lines, the sum is rounded once to
    a whole number of cents, and the result is floored at the program's
    `min_charge_cents`."

    Design: Corner/calculations/min_charge_constant_floors_the_computed_freight
    """
    scenario = fx.setup_single_line_billed_shipment(pro_number="PROC002")

    shipment = fx.get_shipment(scenario["shipment_id"])
    line = fx.get_shipment_line(scenario["line_ids"][0])

    assert shipment["original_charge_cents"] == 12500, (
        f"the raw 9937 cents is floored by min_charge_cents, "
        f"got {shipment['original_charge_cents']}"
    )
    assert shipment["assessed_total_cents"] == 12500
    assert line["line_charge_cents"] == 9937, (
        f"the informational per-line amount is not floored by the shipment minimum, "
        f"got {line['line_charge_cents']}"
    )
    assert line["effective_class_code"] == 70
    assert shipment["billing_status"] == "BILLED"


# ==========================================================================
# Where the rating class comes from
# ==========================================================================


def test_an_active_exception_agreement_beats_the_declared_and_bracketed_class():
    """Step two replaces both the declared 70 and the bracketed 85 with 92.5.

    PRD: "If such an agreement exists, the candidate becomes its
    `agreed_class_code`, and the provenance becomes `FAK` when the agreement's
    `agreement_type` is `FAK` and `EXCEPTION_AGREEMENT` otherwise."

    Design: Corner/calculations/exception_agreement_class_beats_bol_and_density_result
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    fx.create_active_exception_agreement(
        env["customer_id"],
        env["commodity_profile_id"],
        "2026-01-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
        agreement_type="EXCEPTION_CLASS",
        agreed_class_code=92.5,
    )

    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PROC003",
        line_specs=[SIX_HUNDRED_POUND_LINE],
        shipment_overrides={"bol_declared_total_weight_lb": 600},
    )
    line = fx.get_shipment_line(scenario["line_ids"][0])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert line["declared_cubic_ft"] == 44.44
    assert line["declared_density_pcf"] == 13.50
    assert line["effective_class_code"] == 92.5, (
        f"the negotiated class overrides the declared 70, "
        f"got {line['effective_class_code']}"
    )
    assert line["classification_source"] == "EXCEPTION_AGREEMENT"
    assert line["class_floor_applied"] is False
    assert shipment["original_charge_cents"] == 17424, (
        f"6 hundredweight at class 92.5 under the 1.15 weight break is 17424, "
        f"got {shipment['original_charge_cents']}"
    )
    assert shipment["assessed_total_cents"] == 17424


def test_a_freight_all_kinds_program_flattens_every_line_to_one_class():
    """Both lines rate at 92.5 even though they were declared 70 and 100.

    PRD: "If no agreement applies but the shipment's pinned pricing program has
    `program_type` `FAK`, the candidate becomes the program's `fak_class_code` and
    the provenance becomes `FAK`."

    Design: Corner/calculations/fak_program_flattens_every_line_to_one_class
    """
    env = fx.setup_pricing_environment(
        clock=CLOCK,
        program_overrides={
            "program_type": "FAK",
            "base_rate_per_cwt_cents": 4200,
            "discount_pct": 0.35,
            "min_charge_cents": 12500,
            "fak_class_code": 92.5,
        },
    )
    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PROC004",
        line_specs=[FOUR_HUNDRED_POUND_LINE, SEVEN_HUNDRED_POUND_LINE],
        shipment_overrides={"bol_declared_total_weight_lb": 1100},
    )

    first = fx.get_shipment_line(scenario["line_ids"][0])
    second = fx.get_shipment_line(scenario["line_ids"][1])
    shipment = fx.get_shipment(scenario["shipment_id"])
    customer = fx.get_customer(env["customer_id"])

    assert first["effective_class_code"] == 92.5
    assert first["classification_source"] == "FAK"
    assert second["effective_class_code"] == 92.5
    assert second["classification_source"] == "FAK"
    assert first["line_charge_cents"] == 10101
    assert second["line_charge_cents"] == 17677
    assert shipment["original_charge_cents"] == 27778, (
        f"27777.75 is rounded once over the summed amount, "
        f"got {shipment['original_charge_cents']}"
    )
    assert customer["active_program_type"] == "FAK"


def test_one_weight_break_factor_is_derived_from_the_shipment_total():
    """A 1100-pound shipment uses 1.00 on both lines, not 1.30 and 1.15.

    PRD: "Adding the rating weights across all lines gives the shipment's rating
    weight, and one weight-break factor is derived from that shipment total and
    applied identically to every line."

    Design: Corner/calculations/shipment_weight_break_is_derived_from_the_line_total
    """
    scenario = fx.setup_two_line_billed_shipment(pro_number="PROC005")

    shipment = fx.get_shipment(scenario["shipment_id"])
    first = fx.get_shipment_line(scenario["line_ids"][0])
    second = fx.get_shipment_line(scenario["line_ids"][1])

    assert shipment["declared_total_weight_lb"] == 1100
    assert shipment["original_charge_cents"] == 26754, (
        f"a per-line weight break would have produced 31914, "
        f"got {shipment['original_charge_cents']}"
    )
    assert first["line_charge_cents"] == 7644
    assert second["line_charge_cents"] == 19110
    assert second["declared_cubic_ft"] == 74.07
    assert second["declared_density_pcf"] == 9.45
    assert shipment["assessed_total_cents"] == 26754


# ==========================================================================
# The two calculations that select their own input set
# ==========================================================================


def test_the_migration_model_counts_only_billed_freight():
    """An identical unbilled shipment contributes to neither leg of the model.

    PRD: "Its shipment set is every shipment of the program's shipper whose
    `billing_status` is `BILLED`, `REBILLED`, `CREDITED` or `CLOSED`, iterated in
    ascending `created_at`; shipments still `UNBILLED` are excluded from both the
    baseline and the model."

    Design: Corner/calculations/migration_model_input_set_excludes_unbilled_shipments
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    billed = fx.setup_billed_shipment(env=env, pro_number="PROC006")
    unbilled = fx.setup_shipment_with_lines(env, "PROC007")
    candidate = fx.create_rate_program(
        env["customer_id"],
        program_type="DENSITY_BASED",
        base_rate_per_cwt_cents=4200,
        discount_pct=0.35,
        min_charge_cents=12500,
    )

    approved = fx.approve_rate_program(candidate["id"])

    assert_rate_program(approved)
    assert approved["status"] == "APPROVED"
    assert approved["pinned_tariff_version_id"] == env["tariff_version_id"]
    assert approved["modeled_shipment_count"] == 1, (
        f"only the billed shipment is in the input set, "
        f"got {approved['modeled_shipment_count']}"
    )
    assert approved["baseline_revenue_cents"] == 12500
    assert approved["modeled_annual_revenue_cents"] == 42588, (
        f"a density of 1.88 brackets to class 300, giving 42588, "
        f"got {approved['modeled_annual_revenue_cents']}"
    )
    assert approved["modeled_delta_pct"] == 2.4070
    assert approved["migration_recommendation"] == "MIGRATE_DENSITY_BASED"
    assert fx.get_shipment(unbilled["shipment_id"])["billing_status"] == "UNBILLED"
    assert fx.get_shipment(billed["shipment_id"])["billing_status"] == "BILLED"


def test_an_inspection_only_notice_rates_the_reclassed_leg_on_declared_weight():
    """With no capture there is no measured weight, so the delta is purely the class.

    PRD: "on the reclassed basis the rating weight is the line's
    `measured_weight_lb` where one exists and its `declared_weight_lb` otherwise,
    and the rating class is the line's `effective_class_code`."

    Design: Corner/calculations/audit_final_variant_falls_back_to_declared_weight_when_unmeasured
    """
    scenario = fx.setup_single_line_billed_shipment(pro_number="PROC008")
    fx.record_and_accept_finding(
        scenario["line_ids"][0],
        found_class_code=250,
        evidence_photo_count=3,
        notes="Voids between cartons; effective density far below declared",
    )

    notice = fx.draft_manual_notice(scenario["shipment_id"], notice_type="RECLASS")
    fx.issue_notice(notice["id"])

    line = fx.get_shipment_line(scenario["line_ids"][0])
    issued = fx.get_notice(notice["id"])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert_correction_notice(issued)
    assert line["measured_weight_lb"] is None, (
        "no capture was ever recorded against this shipment"
    )
    assert line["effective_class_code"] == 250
    assert line["classification_source"] == "INSPECTION"
    assert issued["origin"] == "AUDITOR_MANUAL"
    assert issued["uses_inspection_findings"] is True
    assert issued["evidence_bundle_count"] == 4, (
        f"nothing for the absent capture, one for the finding and three photos is 4, "
        f"got {issued['evidence_bundle_count']}"
    )
    assert issued["final_delta_cents"] == 22990, (
        f"35490 at class 250 on the declared 400 pounds less the 12500 original is "
        f"22990, got {issued['final_delta_cents']}"
    )
    assert issued["applied_delta_cents"] == 22990
    assert issued["inspection_fee_cents"] == 4500
    assert shipment["assessed_total_cents"] == 39990
    assert shipment["billing_status"] == "REBILLED"
    assert shipment["class_status"] == "RECLASSED"

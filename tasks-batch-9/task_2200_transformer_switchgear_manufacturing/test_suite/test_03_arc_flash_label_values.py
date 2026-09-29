"""Arc-flash label computation: the kV-factor tiers and the ceiling rounding."""

from test_helpers import (
    COMPLIANCE_OFFICER,
    QUALITY_ENGINEER,
    TEST_ENGINEER,
    assert_arc_flash_unlabelable,
    assert_arc_flash_values,
    create_bay,
    create_component,
    create_fat,
    create_label,
    create_order,
    create_report,
    create_supplier,
    drive_order_to_in_production,
    issue_report,
    schedule_fat,
    set_clock,
    start_fat,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId


def _order_with_issued_report(
    api,
    tag,
    rated_kv,
    window_start_at,
    start_clock_at,
    report_overrides,
):
    """An order at IN_PRODUCTION whose FAT carries one ISSUED PASS report."""
    supplier = create_supplier(
        api, supplier_code=f"SUP-{tag}", legal_name=f"{tag} Gear", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number=f"BRK-{tag}",
        category="BREAKER_FRAME",
        lead_time_days=25,
        quantity_on_hand=5,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number=f"TX-{tag}",
        product_family="MV_SWITCHGEAR",
        rated_kv=rated_kv,
        contract_value_cents=900000,
    )
    bay = create_bay(
        api, bay_code=f"BAY-{tag}", max_kv=38, changeover_buffer_hours=2
    )
    material = drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=1,
        priority_class=3,
        need_by_date="2026-07-01T00:00:00Z",
        drawing_set_code=f"DS-{tag}",
    )
    # PRD 3.6 gates report creation on a parent test that is `IN_PROGRESS`, and
    # label generation requires only an `ISSUED` report with a `PASS` verdict — it
    # never requires the FAT itself to have concluded. The test is therefore left
    # running so that a second report may still be measured against it.
    fat = create_fat(
        api, order["id"], test_duration_hours=6, witness_required=False
    )
    schedule_fat(api, fat["id"], bay["id"], window_start_at)
    set_clock(api, start_clock_at)
    start_fat(api, fat["id"])
    report = create_report(api, fat["id"], **report_overrides)
    issue_report(api, report["id"])
    return order, material["drawing"], {"fat": fat, "report": report}


def test_kv_factor_tier_boundary_flips_ppe_category_on_identical_readings(api):
    """PRD 3.6: "A voltage factor is selected by tier: it is 1.00 when `rated_kv`
    is 15 or less, 1.25 when `rated_kv` is above 15 and at most 38, and 1.60 when
    `rated_kv` is above 38."

    Design: Difficulty/combinatorial_formula/arc_flash_kv_factor_tier_15_vs_15_5_flips_ppe_category_on_identical_readings
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    readings = {
        "winding_temp_rise_c": 50,
        "temp_rise_limit_c": 65,
        "short_circuit_current_ka": 20,
        "arc_duration_ms": 150,
        "working_distance_mm": 455,
    }

    order_low, drawing_low, outcome_low = _order_with_issued_report(
        api, "KVA", 15, "2026-02-10T08:00:00Z", "2026-02-10T09:00:00Z", readings
    )
    label_low = create_label(
        api, order_low["id"], drawing_low["id"], outcome_low["report"]["id"]
    )
    generated_low = validate_success(
        api.generate_compliance_label(label_low["id"], {}, COMPLIANCE_OFFICER)
    )
    assert generated_low["status"] == "GENERATED"
    assert_arc_flash_values(
        generated_low,
        incident_energy_cal_cm2=7.5,
        ppe_category=2,
        arc_flash_boundary_mm=1132,
        rating_text="15kV / 20kA / PPE 2",
    )

    order_high, drawing_high, outcome_high = _order_with_issued_report(
        api, "KVB", 15.5, "2026-02-12T08:00:00Z", "2026-02-12T09:00:00Z", readings
    )
    label_high = create_label(
        api, order_high["id"], drawing_high["id"], outcome_high["report"]["id"]
    )
    generated_high = validate_success(
        api.generate_compliance_label(label_high["id"], {}, COMPLIANCE_OFFICER)
    )
    assert generated_high["status"] == "GENERATED"
    assert_arc_flash_values(
        generated_high,
        incident_energy_cal_cm2=9.3,
        ppe_category=3,
        arc_flash_boundary_mm=1265,
    )


def test_incident_energy_ceiling_makes_one_millisecond_the_labelability_line(api):
    """PRD 3.6: "The resulting `incident_energy_cal_cm2` is rounded **up** —
    ceiling, never half up — to one decimal place"; and "An energy of exactly 40.0
    or above is not category 4 at all: no arc-flash label may lawfully be produced
    for such an assembly, and the generation attempt is refused with
    `ERR_ARC_ENERGY_UNLABELABLE`, leaving the label in `DRAFT` with no computed
    values written."

    Design: Difficulty/boundary_precision_check/arc_flash_ceiling_rounding_39_9_labelable_vs_40_0_unlabelable_one_millisecond_apart
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    base_readings = {
        "winding_temp_rise_c": 50,
        "temp_rise_limit_c": 65,
        "short_circuit_current_ka": 25,
        "working_distance_mm": 455,
    }
    order, drawing, outcome = _order_with_issued_report(
        api,
        "BND12",
        15,
        "2026-02-10T08:00:00Z",
        "2026-02-10T09:00:00Z",
        dict(base_readings, arc_duration_ms=645),
    )
    first_report = outcome["report"]

    # 645 ms: a raw 39.879... ceilings to exactly 39.9 and is still labelable.
    label_one = create_label(api, order["id"], drawing["id"], first_report["id"])
    generated = validate_success(
        api.generate_compliance_label(label_one["id"], {}, COMPLIANCE_OFFICER)
    )
    assert generated["status"] == "GENERATED"
    assert_arc_flash_values(
        generated,
        incident_energy_cal_cm2=39.9,
        ppe_category=4,
        arc_flash_boundary_mm=2623,
    )

    # 646 ms on the same test: a raw 39.941... ceilings to exactly 40.0.
    second_report = create_report(
        api, outcome["fat"]["id"], **dict(base_readings, arc_duration_ms=646)
    )
    issue_report(api, second_report["id"])

    superseded = validate_success(
        api.get_test_report(first_report["id"], TEST_ENGINEER)
    )
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["pass_result"] == "PASS"
    reissued = validate_success(api.get_test_report(second_report["id"], TEST_ENGINEER))
    assert reissued["status"] == "ISSUED"
    assert reissued["pass_result"] == "PASS"

    label_two = create_label(api, order["id"], drawing["id"], second_report["id"])
    validate_error(
        api.generate_compliance_label(label_two["id"], {}, COMPLIANCE_OFFICER),
        ApiErrorId.ARC_ENERGY_UNLABELABLE,
        422,
    )
    assert_arc_flash_unlabelable(
        validate_success(api.get_compliance_label(label_two["id"], QUALITY_ENGINEER))
    )

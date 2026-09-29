"""Scheduling a second attempt drags the fulfillment dimension backwards."""

from test_helpers import (
    MATERIALS_PLANNER,
    TEST_ENGINEER,
    assert_bay_scheduled_hours,
    assert_component_buckets,
    assert_component_conservation,
    conclude_fat,
    create_bay,
    create_component,
    create_fat,
    create_order,
    create_report,
    create_supplier,
    drive_order_to_in_production,
    issue_report,
    read_bay,
    read_component,
    read_order,
    run_fat_to_conclusion,
    schedule_fat,
    set_clock,
    start_fat,
)
from prd_bench_local_runner.testing import validate_success


def test_scheduling_attempt_two_reverts_fat_complete_to_in_production(api):
    """PRD 3.5: "Where the scheduled test carries an `attempt_number` greater
    than 1, the order's `fulfillment_status` reverts from `FAT_COMPLETE` to
    `IN_PRODUCTION` at that moment"; on PASS "every allocation on the order in
    status `COMMITTED` becomes `CONSUMED`".

    Design: Difficulty/non_linear_state_machine/order_fulfillment_reverts_fat_complete_to_in_production_on_attempt_two_schedule
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-N06", legal_name="Harbor Coil Works", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="COIL-N6",
        category="CORE_STEEL_COIL",
        lead_time_days=45,
        quantity_on_hand=8,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number="TX-NLS-0006",
        customer_name="Harbor Transit Authority",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=3000000,
        sold_at="2026-02-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    material = drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=2,
        need_by_date="2026-07-01T00:00:00Z",
        drawing_set_code="DS-N6",
    )
    bay = create_bay(
        api, bay_code="BAY-NL6", max_kv=145, changeover_buffer_hours=4,
        supports_impulse=True,
    )

    first = run_fat_to_conclusion(
        api,
        order["id"],
        bay["id"],
        "2026-02-10T08:00:00Z",
        "2026-02-10T09:00:00Z",
        result="PASS",
        fat_overrides={"test_duration_hours": 8, "witness_required": False},
        report_overrides={"winding_temp_rise_c": 65, "temp_rise_limit_c": 65},
    )
    # A reading exactly at the contractual limit passes.
    first_report = validate_success(
        api.get_test_report(first["report"]["id"], TEST_ENGINEER)
    )
    assert first_report["pass_result"] == "PASS"
    assert first_report["failed_criteria"] == []
    assert first["fat"]["status"] == "PASSED"
    assert read_order(api, order["id"])["fulfillment_status"] == "FAT_COMPLETE"
    assert validate_success(
        api.get_component_allocation(material["allocation"]["id"], MATERIALS_PLANNER)
    )["status"] == "CONSUMED"

    # A fresh first attempt scheduled while the order is already FAT_COMPLETE
    # must not revert anything: the side effect is gated on attempt_number.
    fat_two = create_fat(
        api, order["id"], test_duration_hours=8, witness_required=False
    )
    assert fat_two["attempt_number"] == 1
    assert fat_two["retest_of_fat_id"] is None
    schedule_fat(api, fat_two["id"], bay["id"], "2026-02-11T08:00:00Z")
    assert read_order(api, order["id"])["fulfillment_status"] == "FAT_COMPLETE"

    set_clock(api, "2026-02-11T09:00:00Z")
    start_fat(api, fat_two["id"])
    second_report = create_report(
        api, fat_two["id"], winding_temp_rise_c=70, temp_rise_limit_c=65
    )
    issued = issue_report(api, second_report["id"])
    assert issued["pass_result"] == "FAIL"
    assert issued["failed_criteria"] == ["TEMP_RISE"]
    failed = conclude_fat(api, fat_two["id"], "FAIL")
    assert failed["status"] == "FAILED"

    fat_three = create_fat(
        api,
        order["id"],
        test_duration_hours=8,
        witness_required=False,
        retest_of_fat_id=fat_two["id"],
    )
    assert fat_three["attempt_number"] == 2
    assert fat_three["retest_of_fat_id"] == fat_two["id"]
    assert validate_success(
        api.get_factory_acceptance_test(fat_two["id"], TEST_ENGINEER)
    )["status"] == "ABANDONED"
    assert validate_success(
        api.get_factory_acceptance_test(first["fat"]["id"], TEST_ENGINEER)
    )["status"] == "PASSED"

    schedule_fat(api, fat_three["id"], bay["id"], "2026-02-12T08:00:00Z")
    reverted = read_order(api, order["id"])
    assert reverted["fulfillment_status"] == "IN_PRODUCTION"

    # The revert does not un-consume material: an IN_PRODUCTION order with zero
    # committed allocations is a state the forward path cannot produce.
    assert validate_success(
        api.get_component_allocation(material["allocation"]["id"], MATERIALS_PLANNER)
    )["status"] == "CONSUMED"
    final_component = read_component(api, component["id"])
    assert_component_buckets(
        final_component,
        quantity_committed=0,
        quantity_consumed=2,
        quantity_on_hand=6,
    )
    assert_component_conservation(final_component, 8)
    # PRD 3.5: only BAY_SCHEDULED, WITNESS_CONFIRMED and IN_PROGRESS tests occupy
    # a bay, so the PASSED first attempt and the ABANDONED second contribute
    # nothing and the total is fat_three's eight hours alone.
    assert_bay_scheduled_hours(read_bay(api, bay["id"]), 8)

"""Derived reads: availability terms, punch aggregates, the stage-billing
waterfall, the opening quality index and the bay occupation window."""

from test_helpers import (
    CONTRACT_ADMIN,
    FIELD_SERVICE_ENGINEER,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    QUALITY_ENGINEER,
    TEST_ENGINEER,
    assert_bay_scheduled_hours,
    assert_component_buckets,
    assert_instant_equals,
    assert_order_state,
    assert_punch_aggregates,
    assert_quality_indices,
    component_allocation_payload,
    create_allocation,
    create_bay,
    create_component,
    create_fat,
    create_job,
    create_order,
    create_release,
    create_supplier,
    drive_order_to_in_production,
    punch_list_item_payload,
    read_component,
    read_order,
    schedule_fat,
    set_clock,
    supplier_payload,
)
from prd_bench_local_runner.testing import validate_success

_CLOCK = "2026-03-02T08:00:00Z"


def _order(api, order_number):
    return create_order(
        api,
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )


def _component(api, suffix, category, lead_time_days, quantity_on_hand):
    supplier = create_supplier(
        api,
        supplier_code="SUP-%s-01" % suffix,
        legal_name="Copperline Windings AG",
        region="NA",
    )
    return create_component(
        api,
        supplier["id"],
        part_number="PN-%s-01" % suffix,
        category=category,
        lead_time_days=lead_time_days,
        quantity_on_hand=quantity_on_hand,
        allocation_policy="PROTECTED",
    )


def test_a_released_allocation_leaves_every_bucket_it_ever_touched(api):
    """PRD 2.9: "`quantity_reserved`, `quantity_committed` and `quantity_consumed`
    are each the sum of allocation `quantity` over the component's allocations in
    status `RESERVED`, `COMMITTED` and `CONSUMED` respectively; allocations in
    status `RELEASED` or `PREEMPTED` contribute to none of the three."

    Design: Corner/calculations/component_availability_excludes_released_allocations_from_every_term
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CA1")
    component = _component(api, "CA1", "VACUUM_INTERRUPTER", 60, 10)
    allocation = create_allocation(
        api,
        component["id"],
        order["id"],
        quantity=4,
        priority_class=3,
        need_by_date="2026-09-01T00:00:00Z",
    )

    released = validate_success(
        api.release_component_allocation(
            allocation["id"], {"reason": "Duplicate reservation"}, MATERIALS_PLANNER
        )
    )
    assert released["status"] == "RELEASED"

    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_on_hand=10,
        quantity_reserved=0,
        quantity_committed=0,
        quantity_consumed=0,
        quantity_available=10,
    )
    body = api.list_component_allocations(
        MATERIALS_PLANNER,
        {"long_lead_component_id": component["id"], "status": "RELEASED"},
    ).json()
    assert body["meta"]["total_count"] == 1


def test_a_job_with_no_punch_items_reports_itself_complete_not_empty(api):
    """PRD 3.8: "The job is born `SCHEDULED` with `open_punch_count` and
    `blocking_punch_count` at 0, `demobilization_round` at 0,
    `startup_certificate_issued` false, and `completion_ratio_bp` at 10000 — a job
    with no punch items reports itself fully complete rather than empty."

    Design: Corner/calculations/punch_completion_ratio_on_job_with_zero_punch_items_reports_ten_thousand_bp
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CA2")
    release = create_release(api, order["id"])
    job = create_job(
        api, order["id"], release["id"], mobilization_at="2026-06-01T08:00:00Z"
    )
    assert job["status"] == "SCHEDULED"
    assert_punch_aggregates(
        job, open_punch_count=0, blocking_punch_count=0, completion_ratio_bp=10000
    )
    assert job["energized_at"] is None
    assert job["startup_certificate_issued"] is False
    assert job["demobilization_round"] == 0

    body = api.list_commissioning_jobs(
        PLANT_ADMIN, {"engineered_order_id": order["id"]}
    ).json()
    assert body["meta"]["total_count"] == 1


def test_the_three_punch_counters_diverge_on_two_open_items(api):
    """PRD 3.8: "The `open_punch_count` is the number of items on the job whose
    status is `OPEN`, `ASSIGNED` or `RESOLVED`. The `blocking_punch_count` is the
    number of items on the job whose `severity` is `BLOCKING` and whose status is
    neither `CLOSED` nor `REJECTED`... otherwise it is the closed count multiplied
    by 10000, divided by the total, and rounded **down** to whole basis points."

    Design: Corner/calculations/punch_counters_reflect_blocking_severity_across_two_open_items
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CA3")
    release = create_release(api, order["id"])
    job = create_job(
        api, order["id"], release["id"], mobilization_at="2026-06-01T08:00:00Z"
    )
    validate_success(
        api.create_punch_list_item(
            job["id"],
            punch_list_item_payload(
                severity="BLOCKING", description_text="Bushing torque out of spec"
            ),
            FIELD_SERVICE_ENGINEER,
        ),
        201,
    )

    minor = validate_success(
        api.create_punch_list_item(
            job["id"],
            punch_list_item_payload(
                severity="MINOR", description_text="Touch-up paint on cabinet door"
            ),
            QUALITY_ENGINEER,
        ),
        201,
    )
    assert minor["status"] == "OPEN"
    assert minor["severity"] == "MINOR"
    assert minor["reject_count"] == 0

    assert_punch_aggregates(
        validate_success(api.get_commissioning_job(job["id"], FIELD_SERVICE_ENGINEER)),
        open_punch_count=2,
        blocking_punch_count=1,
        completion_ratio_bp=0,
    )
    body = api.list_job_punch_list_items(job["id"], PLANT_ADMIN, {"status": "OPEN"}).json()
    assert body["meta"]["total_count"] == 2


def test_the_only_stage_is_the_remainder_holder_and_takes_the_whole_contract(api):
    """PRD 3.7: "Each stage's provisional amount is the order's
    `net_contract_value_cents` multiplied by that stage's `stage_share_bp`, divided
    by 10000, and rounded **down** to whole cents... The whole remainder goes to a
    single remainder holder: the one stage whose `is_final_stage` is true."

    Design: Corner/calculations/single_final_stage_shipment_release_bills_entire_net_contract_value
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CA4")
    release = create_release(
        api, order["id"], stage_index=1, stage_share_bp=10000, is_final_stage=True
    )
    assert release["status"] == "HELD"
    assert release["stage_index"] == 1
    assert release["stage_billing_cents"] == 4000000
    assert release["is_final_stage"] is True
    assert release["storage_fee_accrued_cents"] == 0
    assert release["cleared_at"] is None

    summary = validate_success(
        api.get_order_financial_summary(order["id"], CONTRACT_ADMIN)
    )
    assert summary["net_contract_value_cents"] == 4000000
    assert summary["billed_to_date_cents"] == 0


def test_a_receipt_event_only_grows_the_denominator_of_a_spotless_supplier(api):
    """PRD 3.9: "The index is 100.00 less the penalty"; and "a `MaterialsPlanner`
    or `QualityEngineer` records one with an optional `event_count`, which
    increases the supplier's `receipt_event_count`, grows the index denominator,
    re-runs both variants"; a supplier only leaves `APPROVED` when the trailing
    index "recomputes to strictly below 70.00".

    Design: Corner/calculations/new_supplier_starts_at_index_one_hundred_and_receipt_event_increments_denominator
    """
    set_clock(api, _CLOCK)
    supplier = validate_success(
        api.create_supplier(
            supplier_payload(
                supplier_code="SUP-CA5-01",
                legal_name="Copperline Windings AG",
                region="APAC",
            ),
            QUALITY_ENGINEER,
        ),
        201,
    )

    recorded = validate_success(
        api.create_receipt_event(supplier["id"], {"event_count": 3}, MATERIALS_PLANNER)
    )
    assert recorded["receipt_event_count"] == 3
    assert recorded["attributed_failure_count"] == 0
    assert_quality_indices(recorded, 100.00, 100.00)
    assert recorded["status"] == "APPROVED"
    assert recorded["probation_entered_at"] is None

    summary = validate_success(
        api.get_supplier_quality_summary(supplier["id"], QUALITY_ENGINEER)
    )
    assert_quality_indices(summary, 100.00, 100.00)


def test_draining_availability_to_exactly_zero_is_the_last_accepted_quantity(api):
    """PRD 2.9: "`quantity_available` is `quantity_on_hand` less
    `quantity_reserved` less `quantity_committed`, and never goes negative."

    Design: Corner/calculations/exact_drain_allocation_of_every_available_unit_is_accepted
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CA6")
    component = _component(api, "CA6", "TAP_CHANGER", 200, 5)

    allocation = validate_success(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                component["version"],
                quantity=5,
                priority_class=1,
                need_by_date="2026-09-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        201,
    )
    assert allocation["status"] == "RESERVED"
    assert allocation["quantity"] == 5
    assert allocation["preempted_for_allocation_id"] is None
    assert allocation["release_penalty_cents"] == 0

    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_on_hand=5,
        quantity_reserved=5,
        quantity_committed=0,
        quantity_available=0,
    )


def test_the_changeover_buffer_sits_inside_the_window_but_outside_the_hours(api):
    """PRD 3.5: "`window_end_at` is `window_start_at` advanced by the sum of
    `test_duration_hours` and the bay's `changeover_buffer_hours`, expressed in
    hours; the changeover buffer therefore sits **inside** the occupying window
    rather than forming a gap after it"; and scheduling "increases the bay's
    `scheduled_hours_total` by the test's `test_duration_hours` — the buffer hours
    are never added to that running total, only the test hours".

    Design: Corner/calculations/bay_occupation_window_end_includes_changeover_buffer_inside_the_window
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-CA7")
    component = _component(api, "CA7", "HV_BUSHING", 120, 10)
    drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=4,
        need_by_date="2026-09-01T00:00:00Z",
        drawing_set_code="DS-100",
    )
    bay = create_bay(
        api,
        bay_code="BAY-CA7",
        max_kv=38,
        changeover_buffer_hours=4,
        supports_impulse=False,
    )
    fat = create_fat(
        api,
        order["id"],
        test_duration_hours=12,
        witness_required=False,
        requires_impulse=False,
    )

    scheduled = schedule_fat(api, fat["id"], bay["id"], "2026-04-01T08:00:00Z")
    assert scheduled["status"] == "BAY_SCHEDULED"
    assert scheduled["test_bay_id"] == bay["id"]
    assert scheduled["window_start_at"] == "2026-04-01T08:00:00Z"
    assert_instant_equals(scheduled["window_end_at"], "2026-04-02T00:00:00Z")
    assert scheduled["attempt_number"] == 1
    assert scheduled["confirmed_witness_count"] == 0

    occupied = validate_success(api.get_test_bay(bay["id"], TEST_ENGINEER))
    assert_bay_scheduled_hours(occupied, 12)
    assert occupied["status"] == "AVAILABLE"

    assert_order_state(
        read_order(api, order["id"]),
        fulfillment_status="IN_PRODUCTION",
        production_posture="OPEN",
        posture_reason_codes=[],
    )

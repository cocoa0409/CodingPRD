"""Claiming a bay window: the three foreign bay columns the schedule reads, and
the half-open window with the changeover buffer inside it."""

from test_helpers import (
    PLANT_ADMIN,
    TEST_ENGINEER,
    assert_bay_scheduled_hours,
    assert_instant_equals,
    create_bay,
    create_component,
    create_fat,
    create_order,
    create_supplier,
    drive_order_to_in_production,
    read_bay,
    read_order,
    set_clock,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId


def _schedule(api, fat_id, bay_id, window_start_at):
    return api.schedule_factory_acceptance_test(
        fat_id, {"test_bay_id": bay_id, "window_start_at": window_start_at},
        TEST_ENGINEER,
    )


def _read_fat(api, fat_id):
    return validate_success(api.get_factory_acceptance_test(fat_id, TEST_ENGINEER))


def test_schedule_admissibility_is_re_read_from_three_live_bay_columns(api):
    """PRD 3.5: "The chosen bay must be `AVAILABLE`, or the attempt fails with
    `ERR_BAY_UNAVAILABLE`... The order's `rated_kv` must not exceed the bay's
    `max_kv`; an exact equality is acceptable... When the test's
    `requires_impulse` is true the bay's `supports_impulse` must also be true, or
    the attempt fails with `ERR_BAY_IMPULSE_UNSUPPORTED`."

    Design: Difficulty/cross_entity_state_dependency/fat_schedule_reads_three_foreign_test_bay_fields_kv_equality_impulse_and_status
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-XED", legal_name="Cascade Coil Works", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="XED-COIL",
        category="CORE_STEEL_COIL",
        lead_time_days=45,
        quantity_on_hand=10,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number="TX-XED-0001",
        customer_name="Cascade Power",
        product_family="POWER_TRANSFORMER",
        rated_kv=145,
        contract_value_cents=90000000,
        sold_at="2026-01-10T00:00:00Z",
        promised_ship_at="2026-12-15T00:00:00Z",
    )
    drive_order_to_in_production(
        api, order, component["id"], quantity=2, need_by_date="2026-12-01T00:00:00Z"
    )

    bay_alpha = create_bay(
        api, bay_code="BAY-ALPHA", max_kv=145, changeover_buffer_hours=2,
        supports_impulse=False,
    )
    bay_bravo = create_bay(
        api, bay_code="BAY-BRAVO", max_kv=144, changeover_buffer_hours=1,
        supports_impulse=True,
    )
    bay_charlie = create_bay(
        api, bay_code="BAY-CHARLIE", max_kv=400, changeover_buffer_hours=1,
        supports_impulse=True,
    )
    fat_plain = create_fat(
        api, order["id"], test_duration_hours=8, witness_required=False,
        requires_impulse=False,
    )
    fat_impulse = create_fat(
        api, order["id"], test_duration_hours=8, witness_required=False,
        requires_impulse=True,
    )

    # One kV short, read off the foreign bay row.
    validate_error(
        _schedule(api, fat_plain["id"], bay_bravo["id"], "2026-06-01T08:00:00Z"),
        ApiErrorId.BAY_KV_INSUFFICIENT,
        422,
    )
    untouched = _read_fat(api, fat_plain["id"])
    assert untouched["status"] == "REQUESTED"
    assert untouched["test_bay_id"] is None

    # Exact equality of rated_kv and max_kv is admitted.
    claimed = validate_success(
        _schedule(api, fat_plain["id"], bay_alpha["id"], "2026-06-01T08:00:00Z")
    )
    assert claimed["status"] == "BAY_SCHEDULED"
    assert claimed["test_bay_id"] == bay_alpha["id"]
    assert_instant_equals(claimed["window_end_at"], "2026-06-01T18:00:00Z")

    # A free window on the same bay, refused only for its impulse capability.
    validate_error(
        _schedule(api, fat_impulse["id"], bay_alpha["id"], "2026-06-03T08:00:00Z"),
        ApiErrorId.BAY_IMPULSE_UNSUPPORTED,
        422,
    )

    # A bay that satisfies both other columns, refused on status alone.
    validate_success(
        api.patch_test_bay(bay_charlie["id"], {"status": "MAINTENANCE"}, PLANT_ADMIN)
    )
    validate_error(
        _schedule(api, fat_impulse["id"], bay_charlie["id"], "2026-06-03T08:00:00Z"),
        ApiErrorId.BAY_UNAVAILABLE,
        409,
    )

    # The test row was never mutated between the refusal and the success, so
    # admissibility is re-read live rather than snapshotted at creation.
    validate_success(
        api.patch_test_bay(bay_charlie["id"], {"status": "AVAILABLE"}, PLANT_ADMIN)
    )
    admitted = validate_success(
        _schedule(api, fat_impulse["id"], bay_charlie["id"], "2026-06-03T08:00:00Z")
    )
    assert admitted["status"] == "BAY_SCHEDULED"
    assert_instant_equals(admitted["window_end_at"], "2026-06-03T17:00:00Z")

    assert_bay_scheduled_hours(read_bay(api, bay_alpha["id"]), 8)
    assert_bay_scheduled_hours(read_bay(api, bay_bravo["id"]), 0)
    assert_bay_scheduled_hours(read_bay(api, bay_charlie["id"]), 8)
    assert read_order(api, order["id"])["fulfillment_status"] == "IN_PRODUCTION"


def test_bay_window_is_half_open_with_the_buffer_carried_inside_it(api):
    """PRD 3.5: "`window_end_at` is `window_start_at` advanced by the sum of
    `test_duration_hours` and the bay's `changeover_buffer_hours`... the
    changeover buffer therefore sits **inside** the occupying window... a
    candidate whose `window_start_at` exactly equals an existing `window_end_at`
    is accepted"; and "the buffer hours are never added to that running total,
    only the test hours".

    Design: Difficulty/resource_temporal_overlap/bay_window_half_open_boundary_with_changeover_buffer_inside_the_window
    """
    set_clock(api, "2026-06-15T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-OVL", legal_name="Ridgeline Coil", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="OVL-COIL",
        category="CORE_STEEL_COIL",
        lead_time_days=45,
        quantity_on_hand=10,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number="TX-OVL-0001",
        customer_name="Ridgeline Transmission",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=12000000,
        sold_at="2026-02-10T00:00:00Z",
        promised_ship_at="2026-11-20T00:00:00Z",
    )
    drive_order_to_in_production(
        api, order, component["id"], quantity=2, need_by_date="2026-11-01T00:00:00Z"
    )
    bay = create_bay(
        api, bay_code="BAY-OVL", max_kv=145, changeover_buffer_hours=3,
        supports_impulse=False,
    )

    def fat(hours):
        return create_fat(
            api, order["id"], test_duration_hours=hours, witness_required=False,
            requires_impulse=False,
        )

    fat_1, fat_2, fat_3 = fat(6), fat(6), fat(2)

    first = validate_success(_schedule(api, fat_1["id"], bay["id"], "2026-07-01T08:00:00Z"))
    assert first["window_start_at"] == "2026-07-01T08:00:00Z"
    assert_instant_equals(first["window_end_at"], "2026-07-01T17:00:00Z")
    assert_bay_scheduled_hours(read_bay(api, bay["id"]), 6)

    # A plain duration overlap.
    validate_error(
        _schedule(api, fat_2["id"], bay["id"], "2026-07-01T13:00:00Z"),
        ApiErrorId.BAY_WINDOW_CONFLICT,
        409,
    )
    # One minute inside the buffer tail: the buffer is occupancy, not a gap.
    validate_error(
        _schedule(api, fat_2["id"], bay["id"], "2026-07-01T16:59:00Z"),
        ApiErrorId.BAY_WINDOW_CONFLICT,
        409,
    )
    # Exactly on the end instant: the interval is half-open, so this is legal.
    back_to_back = validate_success(
        _schedule(api, fat_2["id"], bay["id"], "2026-07-01T17:00:00Z")
    )
    assert_instant_equals(back_to_back["window_end_at"], "2026-07-02T02:00:00Z")

    # The mirror edge: a candidate ending exactly on an existing start instant.
    mirror = validate_success(
        _schedule(api, fat_3["id"], bay["id"], "2026-07-01T03:00:00Z")
    )
    assert_instant_equals(mirror["window_end_at"], "2026-07-01T08:00:00Z")

    assert_bay_scheduled_hours(read_bay(api, bay["id"]), 14)
    schedule_rows = api.get_test_bay_schedule(bay["id"], TEST_ENGINEER).json()["data"]
    assert len(schedule_rows) == 3

    # Abandonment removes exactly the hours the abandoned test added.
    validate_success(
        api.abandon_factory_acceptance_test(
            fat_2["id"], {"reason": "Customer deferred stage 2 witness"}, TEST_ENGINEER
        )
    )
    assert_bay_scheduled_hours(read_bay(api, bay["id"]), 8)

    # An abandoned row never occupies the bay, so the slot is reusable.
    fat_4 = fat(6)
    reused = validate_success(
        _schedule(api, fat_4["id"], bay["id"], "2026-07-01T17:00:00Z")
    )
    assert_instant_equals(reused["window_end_at"], "2026-07-02T02:00:00Z")
    assert_bay_scheduled_hours(read_bay(api, bay["id"]), 14)
    assert read_order(api, order["id"])["fulfillment_status"] == "IN_PRODUCTION"

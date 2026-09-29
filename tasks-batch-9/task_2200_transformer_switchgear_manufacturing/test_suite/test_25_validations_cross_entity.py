"""Sufficiency, the logical clock, aggregate share totals, parent-order gating,
component status and bay capability."""

from test_helpers import (
    LOGISTICS_COORDINATOR,
    MATERIALS_PLANNER,
    PLANT_ADMIN,
    TEST_ENGINEER,
    assert_bay_scheduled_hours,
    assert_component_buckets,
    component_allocation_payload,
    create_bay,
    create_component,
    create_fat,
    create_order,
    create_supplier,
    drive_order_to_in_production,
    order_version,
    read_component,
    set_clock,
    shipment_release_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId

_CLOCK = "2026-03-02T08:00:00Z"


def _order(api, order_number, **overrides):
    payload = dict(
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )
    payload.update(overrides)
    return create_order(api, **payload)


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


def test_one_unit_past_availability_reserves_nothing_at_all(api):
    """PRD 3.4: "The sufficiency test is that the requested quantity must not
    exceed `quantity_available`; an exact drain is legal, and the first failing
    quantity is one greater than `quantity_available`, reported as
    `ERR_COMPONENT_INSUFFICIENT` with no allocation row created."

    Design: Corner/validations/allocation_one_unit_above_available_returns_component_insufficient
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-V8")
    component = _component(api, "V8", "CORE_STEEL_COIL", 150, 5)

    validate_error(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                component["version"],
                quantity=6,
                priority_class=1,
                need_by_date="2026-09-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        ApiErrorId.COMPONENT_INSUFFICIENT,
        409,
    )
    body = api.list_component_allocations(
        MATERIALS_PLANNER, {"long_lead_component_id": component["id"]}
    ).json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0
    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_reserved=0,
        quantity_available=5,
    )


def test_the_need_by_date_is_judged_against_the_logical_clock(api):
    """PRD 3.4: "A `need_by_date` earlier than the logical clock is rejected with
    `ERR_NEED_BY_DATE_PASSED`."

    Design: Corner/validations/allocation_with_need_by_date_before_logical_clock_returns_need_by_date_passed
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-V9")
    component = _component(api, "V9", "HV_BUSHING", 120, 10)

    validate_error(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                component["version"],
                quantity=2,
                priority_class=2,
                need_by_date="2026-03-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        ApiErrorId.NEED_BY_DATE_PASSED,
        422,
    )
    assert_component_buckets(
        read_component(api, component["id"]),
        quantity_reserved=0,
        quantity_available=10,
    )


def test_a_lone_partial_stage_cannot_close_onto_the_contract_value(api):
    """PRD 3.7: "The sum of `stage_share_bp` across those stages must equal exactly
    10000, and any other total — short or over — is rejected with
    `ERR_STAGE_SHARE_TOTAL_INVALID`."

    Design: Corner/validations/single_shipment_release_with_partial_share_returns_stage_share_total_invalid
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-V10")

    validate_error(
        api.create_shipment_release(
            order["id"],
            shipment_release_payload(
                order["version"],
                stage_index=1,
                stage_share_bp=6000,
                is_final_stage=True,
            ),
            LOGISTICS_COORDINATOR,
        ),
        ApiErrorId.STAGE_SHARE_TOTAL_INVALID,
        422,
    )
    body = api.list_order_shipment_releases(order["id"], LOGISTICS_COORDINATOR).json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0


def test_clearing_freight_is_gated_on_the_parent_order_not_on_the_stage(api):
    """PRD 2.11: "an order whose `fulfillment_status` is not a legal source for the
    requested fulfilment transition yields `ERR_ORDER_FULFILLMENT_STATE_INVALID`
    (HTTP 409)... clearing a release requires `FAT_COMPLETE` or `SHIPPING`."

    Design: Corner/validations/clear_shipment_release_while_order_is_planning_returns_order_fulfillment_state_invalid
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-V11")
    release = validate_success(
        api.create_shipment_release(
            order["id"],
            shipment_release_payload(
                order_version(api, order["id"]),
                stage_index=1,
                stage_share_bp=10000,
                is_final_stage=True,
            ),
            LOGISTICS_COORDINATOR,
        ),
        201,
    )

    validate_error(
        api.clear_shipment_release(release["id"], {}, LOGISTICS_COORDINATOR),
        ApiErrorId.ORDER_FULFILLMENT_STATE_INVALID,
        409,
    )
    held = validate_success(
        api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
    )
    assert held["status"] == "HELD"
    assert held["cleared_at"] is None


def test_an_obsolete_part_is_as_unallocatable_as_a_quarantined_one(api):
    """PRD 3.4: "A component that is `QUARANTINED` or `OBSOLETE` is rejected with
    `ERR_COMPONENT_QUARANTINED`."

    Design: Corner/validations/allocating_an_obsolete_component_returns_component_quarantined
    """
    set_clock(api, _CLOCK)
    order = _order(api, "ORD-CORNER-V13")
    component = _component(api, "V13", "BREAKER_FRAME", 300, 8)

    obsolete = validate_success(
        api.obsolete_component(
            component["id"],
            {"reason": "Superseded by a new frame revision"},
            MATERIALS_PLANNER,
        )
    )
    assert obsolete["status"] == "OBSOLETE"

    validate_error(
        api.create_component_allocation(
            component_allocation_payload(
                component["id"],
                order["id"],
                obsolete["version"],
                quantity=2,
                priority_class=2,
                need_by_date="2026-09-01T00:00:00Z",
            ),
            MATERIALS_PLANNER,
        ),
        ApiErrorId.COMPONENT_QUARANTINED,
        409,
    )
    body = api.list_component_allocations(
        MATERIALS_PLANNER, {"long_lead_component_id": component["id"]}
    ).json()
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0


def test_a_free_bay_that_cannot_hold_the_voltage_is_still_refused(api):
    """PRD 3.5: "The order's `rated_kv` must not exceed the bay's `max_kv`; an
    exact equality is acceptable, and the first failing rating is the smallest
    value above `max_kv`, reported as `ERR_BAY_KV_INSUFFICIENT`."

    Design: Corner/validations/scheduling_a_sixty_nine_kv_order_into_a_thirty_eight_kv_bay_returns_bay_kv_insufficient
    """
    set_clock(api, _CLOCK)
    order = _order(
        api,
        "ORD-CORNER-V14",
        customer_name="Northgate Cooperative",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
    )
    component = _component(api, "V14", "HV_BUSHING", 120, 10)
    drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=4,
        need_by_date="2026-09-01T00:00:00Z",
        drawing_set_code="DS-200",
    )
    bay = create_bay(
        api,
        bay_code="BAY-V14",
        max_kv=38,
        changeover_buffer_hours=2,
        supports_impulse=True,
    )
    fat = create_fat(
        api,
        order["id"],
        test_duration_hours=8,
        witness_required=False,
        requires_impulse=False,
    )

    validate_error(
        api.schedule_factory_acceptance_test(
            fat["id"],
            {"test_bay_id": bay["id"], "window_start_at": "2026-04-01T08:00:00Z"},
            TEST_ENGINEER,
        ),
        ApiErrorId.BAY_KV_INSUFFICIENT,
        422,
    )
    unscheduled = validate_success(
        api.get_factory_acceptance_test(fat["id"], TEST_ENGINEER)
    )
    assert unscheduled["status"] == "REQUESTED"
    assert unscheduled["test_bay_id"] is None
    assert unscheduled["window_start_at"] is None
    assert_bay_scheduled_hours(
        validate_success(api.get_test_bay(bay["id"], PLANT_ADMIN)), 0
    )

"""Bay service work: charges + consumption, bay setup-buffer scheduling, and the
cross-entity build-readiness precondition.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, get_success_data,
    create_member, create_service_bay, create_build_in_state,
    create_scheduled_service_order, create_service_order_payload,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]


def test_service_charge_labor_parts_consumption(api):
    """PRD §3.4: "`labor_total_cents` is the flat labor rate for the service type —
    800 cents for `GRIP`, 1500 cents for `WHEEL`, 500 cents for `WAX`;
    `parts_total_cents` is the sum over the parts lines of the product's
    `unit_price_cents` times its quantity; and `total_cents` is the sum of labor and parts."
    PRD §3.4: "Completion also consumes the reserved parts, lowering each parts
    product's `stock_on_hand` and `stock_reserved` by its quantity, awards loyalty on
    the `total_cents` net amount, and stamps `completed_at`."

    Design: Corner/calculations/service_charge_labor_plus_parts_and_consumption
    """
    order, member, bay, parts = create_scheduled_service_order(
        api, service_type="GRIP",
        parts_spec=[{"price": 500, "qty": 2, "stock": 5, "category": "WAX"}])
    api.start_service_order(order["id"], ASSOC)
    resp = api.complete_service_order(order["id"], ASSOC)
    data = validate_success(resp, 200)
    assert data["labor_total_cents"] == 800
    assert data["parts_total_cents"] == 1000
    assert data["total_cents"] == 1800
    part = get_success_data(api.get_product(parts[0]["id"], SM))
    assert part["stock_on_hand"] == 3
    assert part["stock_reserved"] == 0


def test_service_order_on_assembled_build_returns_not_ready(api):
    """PRD §3.4: "when `build_id` is present — the referenced build to be in
    `SETUP_COMPLETE` or `COMPLETED`, else `ERR_BUILD_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/service_order_requires_build_setup_complete
    """
    build, member, products = create_build_in_state(
        api, target_state="ASSEMBLED",
        lines_spec=[{"price": 6000, "qty": 1, "stock": 3}])
    bay = create_service_bay(api)
    resp = api.create_service_order(create_service_order_payload(
        member["id"], bay["id"], "GRIP",
        "2026-07-07T10:00:00Z", "2026-07-07T11:00:00Z", build_id=build["id"]), ASSOC)
    validate_error(resp, ApiErrorId.ERR_BUILD_NOT_READY.value)


def test_service_order_on_setup_complete_build_succeeds(api):
    """PRD §3.4: "when `build_id` is present — the referenced build to be in
    `SETUP_COMPLETE` or `COMPLETED`, else `ERR_BUILD_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/service_order_requires_build_setup_complete
    """
    build, member, products = create_build_in_state(
        api, target_state="SETUP_COMPLETE",
        lines_spec=[{"price": 6000, "qty": 1, "stock": 3}])
    bay = create_service_bay(api)
    resp = api.create_service_order(create_service_order_payload(
        member["id"], bay["id"], "GRIP",
        "2026-07-07T10:00:00Z", "2026-07-07T11:00:00Z", build_id=build["id"]), ASSOC)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_bay_slot_15_min_after_rejected(api):
    """PRD §2.8: "if the gap between the new `[slot_start, slot_end)` interval and an
    existing one is less than 30 minutes (which includes any overlap), the slot is
    rejected with `ERR_BAY_UNAVAILABLE`. A gap of exactly 30 minutes is acceptable."

    Design: Difficulty/resource_temporal_overlap/service_bay_buffer_separation_rejected
    """
    member = create_member(api)
    bay = create_service_bay(api)
    get_success_data(api.create_service_order(create_service_order_payload(
        member["id"], bay["id"], "WAX",
        "2026-07-09T10:00:00Z", "2026-07-09T11:00:00Z"), ASSOC))
    resp = api.create_service_order(create_service_order_payload(
        member["id"], bay["id"], "GRIP",
        "2026-07-09T11:15:00Z", "2026-07-09T11:45:00Z"), ASSOC)
    validate_error(resp, ApiErrorId.ERR_BAY_UNAVAILABLE.value)


def test_bay_slot_exactly_30_min_apart_allowed(api):
    """PRD §2.8: "if the gap between the new `[slot_start, slot_end)` interval and an
    existing one is less than 30 minutes (which includes any overlap), the slot is
    rejected with `ERR_BAY_UNAVAILABLE`. A gap of exactly 30 minutes is acceptable."

    Design: Difficulty/resource_temporal_overlap/service_bay_buffer_separation_rejected
    """
    member = create_member(api)
    bay = create_service_bay(api)
    get_success_data(api.create_service_order(create_service_order_payload(
        member["id"], bay["id"], "WAX",
        "2026-07-09T10:00:00Z", "2026-07-09T11:00:00Z"), ASSOC))
    resp = api.create_service_order(create_service_order_payload(
        member["id"], bay["id"], "GRIP",
        "2026-07-09T11:30:00Z", "2026-07-09T12:00:00Z"), ASSOC)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"

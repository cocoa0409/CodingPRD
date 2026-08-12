"""Slot temporal rules, shop capacity posture, and parts inventory invariants."""
from test_helpers import (
    ApiErrorId, TEST_USERS, add_car_with_inspection, add_part, add_price_entry,
    api_client, authorize_current_wo, build_work_order, complete_current_wo,
    create_part_payload, create_shop_slot_payload, create_slot,
    create_work_order_payload, get_railcar, make_car_owner_rep_headers,
    make_repair_foreman_headers,
    qa_current_wo, scenario_authorized_wo, setup_shop_ctx, start_current_wo,
    submit_current_wo, assign_slot_current_wo, validate_error, validate_paginated,
    validate_success, assert_part_quantity_invariant,
)

ADMIN = TEST_USERS["shop_admin"]
FOREMAN = "foreman-1"

_HOSE_DEFECTS = [
    {"aar_defect_code": "AAR-1204", "defect_group": "AIR_HOSE",
     "cause_code": "WEAR", "severity": "MAJOR", "location": "A-end"},
    {"aar_defect_code": "AAR-1205", "defect_group": "AIR_HOSE",
     "cause_code": "WEAR", "severity": "MAJOR", "location": "B-end"},
    {"aar_defect_code": "AAR-1206", "defect_group": "AIR_HOSE",
     "cause_code": "WEAR", "severity": "MAJOR", "location": "mid"},
]


def test_slot_create_in_past_rejected():
    """PRD §3.1: "A slot whose `ends_at` is at or before the current logical
    time is rejected with `ERR_SLOT_IN_PAST`".

    Design: Corner/errors/slot_create_in_past_rejected
    """
    ctx = setup_shop_ctx()
    resp = api_client.create_shop_slot(
        create_shop_slot_payload(ctx["shop"]["id"], starts_at="2026-04-30T08:00:00Z",
                                 ends_at="2026-04-30T16:00:00Z"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_SLOT_IN_PAST, expected_status=409)


def test_shop_posture_full_at_exact_capacity_blocks_intake():
    """PRD §2.5: "The shop's computed `current_posture` is `FULL` when booked
    hours are greater than or equal to capacity hours — a booked total exactly
    equal to capacity is `FULL` — otherwise `CONSTRAINED` when booked hours
    reach at least 85 percent of capacity, and otherwise `OPEN`."
    PRD §2.5: "creating a new work order on a day whose posture is `FULL` is
    rejected with `ERR_SHOP_AT_CAPACITY` (409)."

    Design: Corner/calculations/shop_posture_full_at_exact_capacity_blocks_intake
    """
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z",
                         shop_overrides={"stalls": 2, "stall_daily_hours": 8})
    add_price_entry(ctx)
    add_car_with_inspection(ctx, car_number="5001", defects=_HOSE_DEFECTS)
    slot1 = create_slot(ctx["shop"]["id"], starts_at="2026-05-01T08:00:00Z",
                        ends_at="2026-05-01T16:00:00Z", stall_id="S1")
    slot2 = create_slot(ctx["shop"]["id"], starts_at="2026-05-01T08:00:00Z",
                        ends_at="2026-05-01T16:00:00Z", stall_id="S2")

    build_work_order(ctx, lines=[{"job_code": "J-AIR-HOSE", "defect_index": 0}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    assign_slot_current_wo(ctx, slot=slot1)

    shop = validate_success(api_client.get_shop(ctx["shop"]["id"], ADMIN))
    assert shop["current_posture"] == "OPEN", "8 of 16 hours booked is below the 85% ratio"

    build_work_order(ctx, lines=[{"job_code": "J-AIR-HOSE", "defect_index": 1}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    assign_slot_current_wo(ctx, slot=slot2)

    shop = validate_success(api_client.get_shop(ctx["shop"]["id"], ADMIN))
    assert shop["current_posture"] == "FULL", "16 of 16 hours booked hits the >= boundary"

    car = get_railcar(ctx["car"]["id"])
    resp = api_client.create_work_order(
        create_work_order_payload(car["id"], ctx["inspection"]["id"], car["version"]),
        make_repair_foreman_headers(FOREMAN))
    validate_error(resp, ApiErrorId.ERR_SHOP_AT_CAPACITY, expected_status=409)


def test_part_depleted_flip_on_consume():
    """PRD §2.9: "A part's `status` is computed: `DEPLETED` when `on_hand_qty`
    is exactly zero, otherwise `REORDER_NEEDED` when `available_qty` is less
    than or equal to `reorder_threshold` — equality counts — and otherwise
    `ACTIVE`."
    PRD §2.9: "**Consuming** at quality-gate pass decreases `on_hand_qty` by
    the consumed quantity and decreases `reserved_qty` by the planned quantity,
    leaving `available_qty` unchanged by the consumption itself."

    Design: Corner/calculations/part_depleted_flip_on_consume
    """
    ctx = scenario_authorized_wo(
        part={"part_number": "Z-900", "description": "Cotter pin set",
              "unit_price_cents": 250, "on_hand_qty": 1, "reorder_threshold": 0})
    part_id = ctx["parts"]["part"]["id"]
    reserved = validate_success(api_client.get_part(part_id, ADMIN))
    assert reserved["on_hand_qty"] == 1 and reserved["reserved_qty"] == 1
    assert reserved["status"] == "REORDER_NEEDED", (
        "available 0 <= threshold 0 flips REORDER_NEEDED, but on_hand 1 is not DEPLETED")

    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    complete_current_wo(ctx, actual_hours=1.5,
                        parts_used=[[{"part_item_id": part_id, "quantity": 1}]])
    qa_current_wo(ctx, result="PASS")

    part = validate_success(api_client.get_part(part_id, ADMIN))
    assert part["on_hand_qty"] == 0, "consumption drives on_hand to zero"
    assert part["reserved_qty"] == 0
    assert part["status"] == "DEPLETED", "on_hand exactly zero is DEPLETED"
    assert_part_quantity_invariant(part)


def test_authorize_with_insufficient_part_stock_rejected():
    """PRD §3.4: "for every planned part on every line, `available_qty` must be
    at least the planned quantity, or the authorization fails with
    `ERR_PART_STOCK_INSUFFICIENT` and nothing is reserved."

    Design: Corner/validations/authorize_with_insufficient_part_stock_rejected
    """
    ctx = setup_shop_ctx()
    add_price_entry(ctx)
    part = add_part(ctx, key="short", part_number="S-700", description="Hose coupling",
                    unit_price_cents=1200, on_hand_qty=1, reorder_threshold=0)
    add_car_with_inspection(ctx, car_number="6002")
    build_work_order(ctx, lines=[{
        "job_code": "J-AIR-HOSE",
        "planned_parts": [{"part_item_id": part["id"], "quantity": 2}],
    }])
    wo = submit_current_wo(ctx)
    resp = api_client.authorize_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]},
        headers=make_car_owner_rep_headers(ctx["owner"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PART_STOCK_INSUFFICIENT, expected_status=409)
    wo_now = validate_success(api_client.get_work_order(wo["id"], ADMIN))
    assert wo_now["auth_status"] == "PENDING_AUTHORIZATION"
    part_now = validate_success(api_client.get_part(part["id"], ADMIN))
    assert part_now["reserved_qty"] == 0, "no partial reservation may leak"


def test_duplicate_part_number_rejected():
    """PRD §3.1: "a `part_number` unique within the shop — duplicates are
    rejected with `ERR_DUPLICATE_PART_NUMBER`".

    Design: Corner/errors/duplicate_part_number_rejected
    """
    ctx = setup_shop_ctx()
    validate_success(api_client.create_part(
        create_part_payload(ctx["shop"]["id"], part_number="H-100"), ADMIN),
        expected_status=201)
    resp = api_client.create_part(
        create_part_payload(ctx["shop"]["id"], part_number="H-100",
                            description="duplicate", unit_price_cents=4600,
                            on_hand_qty=5, reorder_threshold=1), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PART_NUMBER, expected_status=409)
    _data, meta = validate_paginated(
        api_client.list_parts(ADMIN, params={"shop_id": ctx["shop"]["id"]}))
    assert meta["total_count"] == 1, "duplicate create must not persist"

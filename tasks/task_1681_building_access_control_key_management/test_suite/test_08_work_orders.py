"""Work orders: lifecycle guards, door maintenance coupling, manual-REKEY ban,
and half-open window overlap semantics."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_work_order_payload,
    get_door,
    get_success_data,
    list_work_orders,
    set_clock,
    setup_building_with_chain,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


def test_work_order_complete_from_open_rejected(api):
    """PRD §3.5: "Completing an `IN_PROGRESS` order records the supplied
    `actual_cost_cents` (required at completion), returns the door to
    `OPERATIONAL`, and — for `REKEY` orders only — fires the re-pinning
    cascade: hop 1 re-pins the door by setting `key_node_id` to
    `target_key_node_id`, rotating `bitting_code` to the target node's
    label, and restoring `core_status` to `ACTIVE`;"

    Design: Corner/state_machines/work_order_complete_from_open_rejected
    """
    ctx = setup_building_with_chain("WO House", with_door=True)
    set_clock("2026-08-01T08:00:00Z")
    resp = api.create_work_order(
        create_work_order_payload(ctx["building"]["id"], ctx["door"]["id"],
                                  "HARDWARE_REPAIR", "2026-08-01T10:00:00Z",
                                  "2026-08-01T11:00:00Z"),
        OFFICER,
    )
    wo = validate_success(resp, expected_status=201)

    resp = api.complete_work_order(wo["id"], {"actual_cost_cents": 5000}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE)
    assert validate_success(api.get_work_order(wo["id"], OFFICER))["status"] == "OPEN"


def test_work_order_start_on_maintenance_door_rejected(api):
    """PRD §3.5: "Starting a work order (`OPEN` → `IN_PROGRESS`) requires the
    door's `hardware_status` to be `OPERATIONAL`, else
    `ERR_DOOR_UNDER_MAINTENANCE` (state errors generally surface as
    `ERR_WORK_ORDER_INVALID_STATE`); starting flips the door to
    `UNDER_MAINTENANCE`, and when the order belongs to an `APPROVED` campaign
    this is the event that tips the campaign to `IN_PROGRESS`."

    Design: Corner/validations/work_order_start_on_maintenance_door_rejected
    """
    ctx = setup_building_with_chain("Maint House", with_door=True)
    building, door = ctx["building"], ctx["door"]
    set_clock("2026-08-01T08:00:00Z")
    wo1 = validate_success(api.create_work_order(
        create_work_order_payload(building["id"], door["id"], "HARDWARE_REPAIR",
                                  "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z"),
        OFFICER), expected_status=201)
    validate_success(api.start_work_order(wo1["id"], OFFICER))
    wo2 = validate_success(api.create_work_order(
        create_work_order_payload(building["id"], door["id"], "INSPECTION",
                                  "2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z"),
        OFFICER), expected_status=201)

    resp = api.start_work_order(wo2["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_DOOR_UNDER_MAINTENANCE)
    assert validate_success(api.get_work_order(wo2["id"], OFFICER))["status"] == "OPEN"


def test_work_order_cancel_from_open_keeps_door_operational(api):
    """PRD §3.5: "Cancelling is allowed from `OPEN` only."

    Design: Corner/state_machines/work_order_cancel_from_open_keeps_door_operational
    """
    ctx = setup_building_with_chain("WO Cancel House", with_door=True)
    building, door = ctx["building"], ctx["door"]
    set_clock("2026-08-01T08:00:00Z")
    wo = validate_success(api.create_work_order(
        create_work_order_payload(building["id"], door["id"], "INSPECTION",
                                  "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z"),
        OFFICER), expected_status=201)

    cancelled = validate_success(api.cancel_work_order(wo["id"], OFFICER))
    assert cancelled["status"] == "CANCELLED"
    assert get_door(door["id"])["hardware_status"] == "OPERATIONAL"


def test_manual_rekey_work_order_creation_rejected(api):
    """PRD §3.5: "Note that `REKEY` is reserved for campaign-generated orders; a
    manual work-order creation carrying that type is `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/manual_rekey_work_order_creation_rejected
    """
    ctx = setup_building_with_chain("Manual Rekey House", with_door=True)
    set_clock("2026-08-01T08:00:00Z")
    resp = api.create_work_order(
        create_work_order_payload(ctx["building"]["id"], ctx["door"]["id"], "REKEY",
                                  "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Difficulty: half-open overlap vs adjacency on the door resource
# ---------------------------------------------------------------------------

def _setup_overlap_house():
    ctx = setup_building_with_chain("Schedule House", with_door=True)
    set_clock("2026-08-01T08:00:00Z")
    building, door = ctx["building"], ctx["door"]
    wo_a = validate_success(api_client.create_work_order(
        create_work_order_payload(building["id"], door["id"], "HARDWARE_REPAIR",
                                  "2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z"),
        OFFICER), expected_status=201)
    ctx["wo_a"] = wo_a
    return ctx


def test_work_order_overlap_adjacent_windows_allowed(api):
    """PRD §3.5: "The planned window must not intersect another `OPEN` or
    `IN_PROGRESS` order's window on the same door — windows whose endpoints
    merely touch do not intersect — else `ERR_WORK_ORDER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/work_order_half_open_overlap_vs_adjacency
    """
    ctx = _setup_overlap_house()
    building, door = ctx["building"], ctx["door"]

    # Touching at 12:00 (A's end == B's start): allowed under half-open semantics.
    resp = api.create_work_order(
        create_work_order_payload(building["id"], door["id"], "INSPECTION",
                                  "2026-08-01T12:00:00Z", "2026-08-01T14:00:00Z"),
        OFFICER,
    )
    validate_success(resp, expected_status=201)
    # Touching at 10:00 on the other side: also allowed.
    resp = api.create_work_order(
        create_work_order_payload(building["id"], door["id"], "BATTERY_REPLACE",
                                  "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z"),
        OFFICER,
    )
    validate_success(resp, expected_status=201)

    orders = list_work_orders(door_id=door["id"])
    assert len(orders) == 3
    assert all(o["status"] == "OPEN" for o in orders)


def test_work_order_overlap_true_intersection_rejected(api):
    """PRD §3.5: "The planned window must not intersect another `OPEN` or
    `IN_PROGRESS` order's window on the same door — windows whose endpoints
    merely touch do not intersect — else `ERR_WORK_ORDER_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/work_order_half_open_overlap_vs_adjacency
    """
    ctx = _setup_overlap_house()
    building, door = ctx["building"], ctx["door"]

    # 11:00-12:00 lies strictly inside A's 10:00-12:00 window.
    resp = api.create_work_order(
        create_work_order_payload(building["id"], door["id"], "BATTERY_REPLACE",
                                  "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z"),
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_OVERLAP)
    orders = list_work_orders(door_id=door["id"])
    assert len(orders) == 1

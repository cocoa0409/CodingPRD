"""Wheelset mount/remove/evaluate cycle and serial uniqueness."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_wheelset,
    make_quality_inspector_headers, make_repair_foreman_headers,
    scenario_authorized_wo, assign_slot_current_wo, start_current_wo,
    setup_shop_ctx, validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
PARTS = TEST_USERS["parts_clerk"]
QI = "qi-1"
FOREMAN = "foreman-1"


def test_wheelset_mount_reclaim_cycle_and_condemn_boundaries():
    """PRD §3.5: "mounting against a car in any other status is refused with
    `ERR_CAR_NOT_IN_SHOP`."
    PRD §3.6: "a wheelset is condemned when its flange thickness is at most
    28.0 millimeters or its tread wear is at least 9.5 millimeters — a flange
    of exactly 28.0 or a tread of exactly 9.5 condemns."
    PRD §3.6: "A `REMOVED` wheelset inside both limits — flange greater than
    28.0 and tread under 9.5 — is reclaimed to `IN_STOCK`".

    Design: Corner/state_machines/wheelset_mount_reclaim_cycle_and_condemn_boundaries
    """
    ctx = scenario_authorized_wo()
    assign_slot_current_wo(ctx)
    w1 = create_wheelset(ctx["shop"]["id"], serial_number="WS-001",
                         flange_thickness_mm=30.0, tread_wear_mm=5.0)
    w2 = create_wheelset(ctx["shop"]["id"], serial_number="WS-002",
                         flange_thickness_mm=29.0, tread_wear_mm=9.4)
    foreman = make_repair_foreman_headers(FOREMAN)
    qi = make_quality_inspector_headers(QI)

    # Car still ARRIVED (work not started): mount refused.
    resp = api_client.mount_wheelset(w1["id"], {"railcar_id": ctx["car"]["id"]}, foreman)
    validate_error(resp, ApiErrorId.ERR_CAR_NOT_IN_SHOP, expected_status=409)

    start_current_wo(ctx)
    mounted = validate_success(api_client.mount_wheelset(
        w1["id"], {"railcar_id": ctx["car"]["id"]}, foreman))
    assert mounted["status"] == "MOUNTED"
    assert mounted["mounted_railcar_id"] == ctx["car"]["id"]

    removed = validate_success(api_client.remove_wheelset(w1["id"], foreman))
    assert removed["status"] == "REMOVED"
    assert removed["mounted_railcar_id"] is None

    reclaimed = validate_success(api_client.evaluate_wheelset(
        w1["id"], {"flange_thickness_mm": 29.5, "tread_wear_mm": 4.0}, qi))
    assert reclaimed["status"] == "IN_STOCK", "within both limits reclaims the wheelset"

    condemned_flange = validate_success(api_client.evaluate_wheelset(
        w1["id"], {"flange_thickness_mm": 28.0, "tread_wear_mm": 4.0}, qi))
    assert condemned_flange["status"] == "CONDEMNED", "flange exactly 28.0 condemns (<=)"

    condemned_tread = validate_success(api_client.evaluate_wheelset(
        w2["id"], {"flange_thickness_mm": 30.0, "tread_wear_mm": 9.5}, qi))
    assert condemned_tread["status"] == "CONDEMNED", "tread exactly 9.5 condemns (>=)"


def test_duplicate_wheelset_serial_rejected():
    """PRD §3.1: "a `serial_number` unique within the shop — duplicates fail
    with `ERR_DUPLICATE_WHEELSET_SERIAL`".

    Design: Corner/errors/duplicate_wheelset_serial_rejected
    """
    ctx = setup_shop_ctx()
    create_wheelset(ctx["shop"]["id"], serial_number="WS-001",
                    flange_thickness_mm=30.0, tread_wear_mm=5.0)
    resp = api_client.create_wheelset(
        {"shop_id": ctx["shop"]["id"], "serial_number": "WS-001",
         "flange_thickness_mm": 31.0, "tread_wear_mm": 4.0}, PARTS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_WHEELSET_SERIAL, expected_status=409)

"""Receipt and pick-task transition guards (corner state-machine instances)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_received_receipt,
    stock_client_sku_bin,
    order_in_picking,
    release_single_line_order,
    pick_tasks_for_order,
    TEST_USERS,
)

RECEIVING = TEST_USERS["receiving_clerk_headers"]
PICK = TEST_USERS["pick_operator_headers"]
PACK = TEST_USERS["pack_station_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
WAVE = TEST_USERS["wave_planner_headers"]


def test_receive_already_received_receipt_rejected(api):
    """PRD §3.2: "First, a clerk dock-counts the receipt, supplying the
    `received_qty` actually counted on the dock (which must be at least 0); this
    requires the receipt to be in `ANNOUNCED` status, else `ERR_RECEIPT_NOT_ANNOUNCED`
    (HTTP 409), and a `received_qty` below 0 is rejected as `ERR_INVALID_REQUEST`."

    A second receive on a RECEIVED receipt is rejected; received_qty unchanged.

    Design: Corner/state_machines/receive_from_already_received_receipt_rejected
    """
    client, sku, b, rcpt = setup_received_receipt(expected_qty=5, unit_volume_cc=400)
    assert rcpt["received_qty"] == 5
    resp = api.receive_receipt(client["id"], rcpt["id"], {"received_qty": 9}, RECEIVING)
    validate_error(resp, ApiErrorId.ERR_RECEIPT_NOT_ANNOUNCED.value)
    refreshed = validate_success(api.get_client_receipt(client["id"], rcpt["id"], RECEIVING))
    assert refreshed["status"] == "RECEIVED"
    assert refreshed["received_qty"] == 5


def test_cancel_received_receipt_rejected(api):
    """PRD §3.2: "An announced receipt that has not been counted may instead be
    cancelled, moving `ANNOUNCED` to `CANCELLED`; cancellation likewise requires
    the `ANNOUNCED` status and otherwise raises `ERR_RECEIPT_NOT_ANNOUNCED`."

    Design: Corner/state_machines/cancel_receipt_from_received_state_rejected
    """
    client, sku, b, rcpt = setup_received_receipt(expected_qty=5, unit_volume_cc=400)
    resp = api.cancel_receipt(client["id"], rcpt["id"], RECEIVING)
    validate_error(resp, ApiErrorId.ERR_RECEIPT_NOT_ANNOUNCED.value)
    refreshed = validate_success(api.get_client_receipt(client["id"], rcpt["id"], RECEIVING))
    assert refreshed["status"] == "RECEIVED"


def test_pack_before_picks_confirmed_rejected(api):
    """PRD §3.6: "Packing requires the order to be in `PICKING` status (else
    `ERR_ORDER_NOT_PICKING`) and every pick task for the order to be in `PICKED`
    status (else `ERR_PICKS_INCOMPLETE`)."

    Packing while the single pick task is still ASSIGNED is rejected; order stays PICKING.

    Design: Corner/state_machines/pack_before_all_picks_confirmed_rejected
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=4)
    order, wave = release_single_line_order(client["id"], sku["id"], 2, ship_to_zone=2)
    resp = api.pack_order(client["id"], order["id"], {"cartons": [{"packed_units": 2}]}, PACK)
    validate_error(resp, ApiErrorId.ERR_PICKS_INCOMPLETE.value)
    refreshed = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed["status"] == "PICKING"


def test_confirm_already_picked_task_rejected(api):
    """PRD §3.5: "Confirming a pick requires the task to be in `ASSIGNED` status
    (else `ERR_PICK_NOT_ASSIGNED`) and the bin owning the task's `lot_id` to be
    `OPEN` (else `ERR_BIN_BLOCKED`)."
    PRD §3.5: "A successful confirmation records `picked_qty` and moves the task
    from `ASSIGNED` to `PICKED`."

    A second confirm on an already-PICKED task is rejected; picked_qty unchanged.

    Design: Corner/state_machines/confirm_pick_already_picked_rejected_terminal_lock
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=4)
    order, wave = release_single_line_order(client["id"], sku["id"], 2, ship_to_zone=2)
    pt = pick_tasks_for_order(order["id"])[0]
    validate_success(api.confirm_pick(client["id"], pt["id"], {"picked_qty": 2}, PICK))

    resp = api.confirm_pick(client["id"], pt["id"], {"picked_qty": 2}, PICK)
    validate_error(resp, ApiErrorId.ERR_PICK_NOT_ASSIGNED.value)
    refreshed = validate_success(api.get_pick_task(pt["id"], WAVE))
    assert refreshed["status"] == "PICKED"
    assert refreshed["picked_qty"] == 2

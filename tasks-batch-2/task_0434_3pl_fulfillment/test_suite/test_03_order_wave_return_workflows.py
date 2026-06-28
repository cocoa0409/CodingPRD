"""Order/wave branch workflows, returns grading, and conserved-quantity invariants.

Covers non_linear_state_machine and compensating_invariant difficulty rules, plus
the state-machine corner instances (short, wave cancel, damaged grade, etc.).
"""
import pytest
from test_helpers import (
    validate_success,
    stock_client_sku_bin,
    release_single_line_order,
    confirm_all_picks,
    order_in_picking,
    pick_tasks_for_order,
    pack_order,
    buy_label,
    ship_order,
    setup_shipped_order,
    create_client,
    create_sku,
    create_order,
    order_line,
    lot_for,
    lots_for_sku,
    get_lot,
    get_bin,
    make_client_user_headers,
    TEST_USERS,
)

WAVE = TEST_USERS["wave_planner_headers"]
PICK = TEST_USERS["pick_operator_headers"]
RETURNS = TEST_USERS["returns_clerk_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_order_short_branch_releases_unconfirmed_reservation(api):
    """PRD §3.5: "Declaring short releases the unconsumed reservation for every
    line: for each line the chosen lot's `reserved_qty` is reduced by the
    shortfall — the line's `qty` minus its `picked_qty` — and the lot's
    `available_qty` is increased by that same delta, with the bin's `occupied_cc`
    recomputed."

    A 3-unit pick task confirmed at 2, then short: the 1 unconfirmed reserved unit
    (shortfall = qty 3 - picked_qty 2 = 1) is released, leaving reserved 2 /
    available 8 (the 2 picked-but-unshipped units stay reserved).

    Design: Difficulty/non_linear_state_machine/order_branches_picking_to_short_vs_packed
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=10)
    lot = lot_for(client["id"], sku["id"], b["id"])
    order, wave = release_single_line_order(client["id"], sku["id"], 3, ship_to_zone=2)
    confirm_all_picks(client["id"], order["id"], picked_qty=2)

    shorted = validate_success(api.short_order(client["id"], order["id"], PICK))
    assert shorted["status"] == "SHORT"

    final_lot = get_lot(lot["id"])
    assert final_lot["reserved_qty"] == 2, final_lot
    assert final_lot["available_qty"] == 8, final_lot


def test_pack_branch_creates_cartons_and_stamps_estimate(api):
    """PRD §3.6: "A successful pack creates the cartons, stamps
    `estimated_handling_cents`, and advances the order from `PICKING` to `PACKED`."

    The PACKED branch (contrast SHORT) of the PICKING fork creates a carton and
    moves the order to PACKED.

    Design: Difficulty/non_linear_state_machine/order_branches_picking_to_short_vs_packed
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=10)
    order, wave = order_in_picking(client["id"], sku["id"], 3, ship_to_zone=2)
    packed = pack_order(client["id"], order["id"], [3])
    assert packed["status"] == "PACKED"


def test_wave_cancel_branch_detaches_orders_leaving_imported(api):
    """PRD §3.3: "A building wave may be cancelled, which detaches every member
    order by clearing its `wave_id` back to null (the orders remain `IMPORTED`)
    and moves the wave from `BUILDING` to `CANCELLED`".

    Design: Difficulty/non_linear_state_machine/wave_branches_building_to_released_vs_cancelled
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    order = create_order(client["id"], [order_line(sku["id"], 1)], ship_to_zone=2)
    wave = validate_success(api.create_wave(client["id"], WAVE), expected_status=201)
    validate_success(api.add_order_to_wave(client["id"], wave["id"], {"order_id": order["id"]}, WAVE))

    cancelled = validate_success(api.cancel_wave(client["id"], wave["id"], WAVE))
    assert cancelled["status"] == "CANCELLED"

    refreshed = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed["status"] == "IMPORTED"
    assert refreshed["wave_id"] is None


def test_wave_release_branch_reserves_and_moves_to_picking(api):
    """PRD §3.4: "As release completes, each member order advances from `IMPORTED`
    to `RESERVED` and immediately onward to `PICKING`, and the wave moves from
    `BUILDING` to `RELEASED`."

    The RELEASE branch (contrast CANCEL) of the BUILDING fork.

    Design: Difficulty/non_linear_state_machine/wave_branches_building_to_released_vs_cancelled
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=5)
    order, wave = release_single_line_order(client["id"], sku["id"], 3, ship_to_zone=2)
    assert order["status"] == "PICKING"
    refreshed_wave = validate_success(api.get_client_wave(client["id"], wave["id"], WAVE))
    assert refreshed_wave["status"] == "RELEASED"


def test_ship_then_sellable_return_conserves_on_hand(api):
    """PRD §3.9: "A sellable restock creates or tops up an `InventoryLot` in the
    `bin_id` for the return's `client_id` and `sku_id`, raising both `on_hand_qty`
    and `available_qty` by `qty` and recomputing the bin's `occupied_cc`."

    Ship 2 units (on_hand -> 0), then a SELLABLE return of 2 restocks (on_hand -> 2).

    Design: Difficulty/compensating_invariant/ship_then_sellable_return_conserves_on_hand_qty
    """
    client, sku, b, order, shipment = setup_shipped_order(
        unit_volume_cc=400, order_qty=2, carton_units=[2], ship_to_zone=2,
        carrier_discount_bps=0,
    )
    ret = validate_success(
        api.create_return(client["id"],
                          {"order_id": order["id"], "sku_id": sku["id"], "bin_id": b["id"], "qty": 2},
                          RETURNS),
        expected_status=201,
    )
    graded = validate_success(
        api.grade_return(client["id"], ret["id"], {"grade": "SELLABLE"}, RETURNS)
    )
    assert graded["status"] == "GRADED"
    assert graded["grade"] == "SELLABLE"

    total_on_hand = sum(l["on_hand_qty"] for l in lots_for_sku(sku["id"]))
    assert total_on_hand == 2, total_on_hand
    assert get_bin(b["id"])["occupied_cc"] == 800


def test_sellable_return_recomputes_restock_bin_occupancy(api):
    """PRD §2.7: "Each bin tracks its `occupied_cc`, a read-only figure recomputed
    as the sum, over every `InventoryLot` resting in that bin, of the lot's
    `on_hand_qty` multiplied by the `unit_volume_cc` of its SKU."

    A second assertion on the ship-then-return conservation instance: after the
    restock the bin's recomputed occupied_cc reflects the 2 restocked 400cc units.

    Design: Difficulty/compensating_invariant/ship_then_sellable_return_conserves_on_hand_qty
    """
    client, sku, b, order, shipment = setup_shipped_order(
        unit_volume_cc=400, order_qty=2, carton_units=[2], ship_to_zone=2,
        carrier_discount_bps=0,
    )
    assert get_bin(b["id"])["occupied_cc"] == 0  # consumed at ship
    ret = validate_success(
        api.create_return(client["id"],
                          {"order_id": order["id"], "sku_id": sku["id"], "bin_id": b["id"], "qty": 2},
                          RETURNS),
        expected_status=201,
    )
    validate_success(api.grade_return(client["id"], ret["id"], {"grade": "SELLABLE"}, RETURNS))
    assert get_bin(b["id"])["occupied_cc"] == 800


def test_damaged_return_grade_scraps_no_restock(api):
    """PRD §3.9: "When the `grade` is `DAMAGED`, the units are scrapped and no
    inventory changes."

    Design: Corner/state_machines/damaged_return_grade_scraps_no_restock
    """
    client, sku, b, order, shipment = setup_shipped_order(
        unit_volume_cc=400, order_qty=2, carton_units=[2], ship_to_zone=2,
        carrier_discount_bps=0,
    )
    ret = validate_success(
        api.create_return(client["id"],
                          {"order_id": order["id"], "sku_id": sku["id"], "bin_id": b["id"], "qty": 2},
                          RETURNS),
        expected_status=201,
    )
    graded = validate_success(api.grade_return(client["id"], ret["id"], {"grade": "DAMAGED"}, RETURNS))
    assert graded["status"] == "GRADED"
    assert graded["grade"] == "DAMAGED"

    assert get_bin(b["id"])["occupied_cc"] == 0
    total_on_hand = sum(l["on_hand_qty"] for l in lots_for_sku(sku["id"]))
    assert total_on_hand == 0


def test_close_graded_return_transitions_to_closed(api):
    """PRD §3.9: "A graded return is finally closed by a `ReturnsClerk`, moving
    `GRADED` to `CLOSED`; closing requires the `GRADED` status, else
    `ERR_RETURN_NOT_GRADED`."

    Design: Corner/state_machines/close_return_valid_transition_graded_to_closed
    """
    client, sku, b, order, shipment = setup_shipped_order(
        unit_volume_cc=400, order_qty=2, carton_units=[2], ship_to_zone=2,
        carrier_discount_bps=0,
    )
    ret = validate_success(
        api.create_return(client["id"],
                          {"order_id": order["id"], "sku_id": sku["id"], "bin_id": b["id"], "qty": 1},
                          RETURNS),
        expected_status=201,
    )
    validate_success(api.grade_return(client["id"], ret["id"], {"grade": "DAMAGED"}, RETURNS))
    closed = validate_success(api.close_return(client["id"], ret["id"], RETURNS))
    assert closed["status"] == "CLOSED"
    assert closed["grade"] == "DAMAGED"


def test_deliver_shipment_transitions_labelled_to_delivered(api):
    """PRD §3.8: "A shipped order's standing shipment may later be marked delivered
    by a `ShipStation`, moving the shipment from `LABELLED` to `DELIVERED`;
    delivery requires the shipment to be `LABELLED` (else `ERR_SHIPMENT_NOT_LABELLED`)
    and its order to be `SHIPPED` (else `ERR_ORDER_NOT_SHIPPED`)."

    Design: Corner/state_machines/deliver_shipment_valid_transition_labelled_to_delivered
    """
    client, sku, b, order, shipment = setup_shipped_order(
        unit_volume_cc=400, order_qty=2, carton_units=[2], ship_to_zone=2,
        carrier_discount_bps=0,
    )
    delivered = validate_success(
        api.deliver_shipment(client["id"], shipment["id"], TEST_USERS["ship_station_headers"])
    )
    assert delivered["status"] == "DELIVERED"

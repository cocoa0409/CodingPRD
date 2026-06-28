"""Inventory cascades (putaway/ship), cartonization sizing, cycle counts, and
bin-capacity boundaries.

Covers transitive_cascade and boundary_precision_check difficulty rules, plus the
cartonization and inventory-list corner instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    stock_client_sku_bin,
    order_in_picking,
    pack_order,
    cartons_for_order,
    buy_label,
    ship_order,
    setup_received_receipt,
    setup_lot_with_version,
    putaway_units,
    lot_for,
    lots_for_sku,
    get_bin,
    get_lot,
    create_client,
    create_sku,
    create_bin,
    create_order,
    order_line,
    TEST_USERS,
)

RECEIVING = TEST_USERS["receiving_clerk_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_ship_consumes_lot_and_recomputes_bin(api):
    """PRD §3.8: "On ship, every reserved lot is consumed: each lot's
    `reserved_qty` is reduced by the reserved quantity and its `on_hand_qty` is
    reduced by the same amount, leaving `available_qty` unchanged, with each
    affected bin's `occupied_cc` recomputed."

    A 3-unit order over a 3-unit lot (400cc each) ships -> on_hand 0, occupied_cc 0.

    Design: Difficulty/transitive_cascade/ship_cascades_lot_consumption_bin_recompute_and_handling_ledger
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=3,
                                          handling_surcharge_per_extra_carton_cents=0,
                                          carrier_discount_bps=0)
    lot = lot_for(client["id"], sku["id"], b["id"])
    order, wave = order_in_picking(client["id"], sku["id"], 3, ship_to_zone=3)
    pack_order(client["id"], order["id"], [3])
    buy_label(client["id"], order["id"])
    shipped = ship_order(client["id"], order["id"])

    assert shipped["status"] == "SHIPPED"
    final_lot = get_lot(lot["id"])
    assert final_lot["on_hand_qty"] == 0, final_lot
    assert get_bin(b["id"])["occupied_cc"] == 0


def test_ship_bills_handling_and_credits_balance(api):
    """PRD §3.8: "The server creates a `BillingCharge` whose `charge_type` is
    `HANDLING`, whose `amount_cents` equals the order's `billed_handling_cents`
    exactly, and whose `source_order_id` is the shipped order; posting this charge
    increases the client's `handling_balance_cents` by that `amount_cents`."

    3-unit single-carton order, base 500 + 2*50 = 600 billed (surcharge 0).

    Design: Difficulty/transitive_cascade/ship_cascades_lot_consumption_bin_recompute_and_handling_ledger
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=3,
                                          handling_rate_per_order_cents=500,
                                          handling_rate_per_extra_unit_cents=50,
                                          handling_surcharge_per_extra_carton_cents=0,
                                          carrier_discount_bps=0)
    order, wave = order_in_picking(client["id"], sku["id"], 3, ship_to_zone=3)
    pack_order(client["id"], order["id"], [3])
    buy_label(client["id"], order["id"])
    shipped = ship_order(client["id"], order["id"])

    assert shipped["billed_handling_cents"] == 600
    updated = validate_success(api.get_client(client["id"], BILLING))
    assert updated["handling_balance_cents"] == 600
    charges = _list(api.list_client_billing_charges(client["id"], BILLING,
                                                    params={"source_order_id": order["id"], "charge_type": "HANDLING"}))
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 600
    assert charges[0]["source_order_id"] == order["id"]


def test_putaway_tops_up_lot_then_recomputes_bin(api):
    """PRD §3.2: "putaway creates — or, if one already exists for the same
    combination of `client_id`, `sku_id`, `bin_id`, and originating `receipt_id`,
    tops up — an `InventoryLot`: its `on_hand_qty` and its `available_qty` each
    increase by `received_qty`, the owning bin's `occupied_cc` is recomputed, and
    the receipt advances from `RECEIVED` to `PUTAWAY`."

    5 units * 400cc = 2000cc.

    Design: Difficulty/transitive_cascade/putaway_cascades_lot_topup_then_bin_occupancy
    """
    client, sku, b, rcpt = setup_received_receipt(expected_qty=5, unit_volume_cc=400)
    putaway = validate_success(api.putaway_receipt(client["id"], rcpt["id"], RECEIVING))
    assert putaway["status"] == "PUTAWAY"

    lot = lot_for(client["id"], sku["id"], b["id"])
    assert lot["on_hand_qty"] == 5
    assert lot["available_qty"] == 5
    assert get_bin(b["id"])["occupied_cc"] == 2000


def test_putaway_advances_receipt_and_creates_lot(api):
    """PRD §3.2: "putaway creates — or, if one already exists for the same
    combination of `client_id`, `sku_id`, `bin_id`, and originating `receipt_id`,
    tops up — an `InventoryLot`: its `on_hand_qty` and its `available_qty` each
    increase by `received_qty`, the owning bin's `occupied_cc` is recomputed, and
    the receipt advances from `RECEIVED` to `PUTAWAY`."

    A second assertion on the same chain: the lot is freshly created with the right
    quantities and the receipt records PUTAWAY.

    Design: Difficulty/transitive_cascade/putaway_cascades_lot_topup_then_bin_occupancy
    """
    client, sku, b, rcpt = setup_received_receipt(expected_qty=5, unit_volume_cc=400)
    putaway = validate_success(api.putaway_receipt(client["id"], rcpt["id"], RECEIVING))
    assert putaway["status"] == "PUTAWAY"

    lots = lots_for_sku(sku["id"])
    assert len(lots) == 1
    assert lots[0]["available_qty"] == 5
    assert lots[0]["reserved_qty"] == 0


def test_inventory_lot_listing_reports_computed_quantities(api):
    """PRD §2.8: "a lot's `on_hand_qty` is the physical units present, which equals
    its `reserved_qty` (units committed to picking/packing but not yet shipped)
    plus its `available_qty` (units free to reserve)."

    After a 7-unit putaway with no reservations: on_hand 7, reserved 0, available 7.

    Design: Corner/endpoints/inventory_lots_filtered_list_reverse_reachability_by_bin
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=7)
    lots = _list(api.list_inventory_lots(RECEIVING, params={"bin_id": b["id"]}))
    assert len(lots) == 1, lots
    lot = lots[0]
    assert lot["available_qty"] == 7
    assert lot["reserved_qty"] == 0
    assert lot["on_hand_qty"] == 7


def test_cartonization_fill_exactly_small_inner_is_small(api):
    """PRD §3.6: "A fill at or below 1000 cubic centimetres is a `SMALL` box".
    PRD §3.6: "The boundary is inclusive — a fill of exactly 1000 cubic centimetres
    is `SMALL`."

    2 units * 500cc = 1000cc fill exactly -> SMALL.

    Design: Difficulty/boundary_precision_check/cartonization_fill_equals_small_inner_is_small_inclusive
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=500, stock_qty=2)
    order, wave = order_in_picking(client["id"], sku["id"], 2, ship_to_zone=2)
    packed = pack_order(client["id"], order["id"], [2])
    assert packed["status"] == "PACKED"

    cartons = cartons_for_order(order["id"])
    assert len(cartons) == 1
    assert cartons[0]["fill_volume_cc"] == 1000
    assert cartons[0]["carton_size"] == "SMALL"


def test_cartonization_pack_advances_order_to_packed(api):
    """PRD §3.6: "A successful pack creates the cartons, stamps
    `estimated_handling_cents`, and advances the order from `PICKING` to `PACKED`."

    A second assertion on the boundary instance: the exactly-1000cc carton packs
    successfully and the order transitions to PACKED with one carton recorded.

    Design: Difficulty/boundary_precision_check/cartonization_fill_equals_small_inner_is_small_inclusive
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=500, stock_qty=2)
    order, wave = order_in_picking(client["id"], sku["id"], 2, ship_to_zone=2)
    packed = pack_order(client["id"], order["id"], [2])
    assert packed["status"] == "PACKED"
    cartons = cartons_for_order(order["id"])
    assert len(cartons) == 1
    assert cartons[0]["carton_size"] == "SMALL"


def test_cartonization_fill_just_over_small_is_medium(api):
    """PRD §3.6: "a fill above 1000 but at or below 5000 cubic centimetres is a
    `MEDIUM` box".

    1 unit * 1001cc = 1001cc fill -> MEDIUM (one over the inclusive SMALL boundary).

    Design: Corner/calculations/cartonization_fill_just_over_small_boundary_is_medium
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=1001, stock_qty=2)
    order, wave = order_in_picking(client["id"], sku["id"], 1, ship_to_zone=2)
    pack_order(client["id"], order["id"], [1])

    cartons = cartons_for_order(order["id"])
    assert len(cartons) == 1
    assert cartons[0]["fill_volume_cc"] == 1001
    assert cartons[0]["carton_size"] == "MEDIUM"


def test_carton_overflow_when_fill_exceeds_large(api):
    """PRD §3.6: "A carton whose `fill_volume_cc` exceeds 20000 cubic centimetres
    cannot be boxed and is rejected with `ERR_CARTON_OVERFLOW` (HTTP 409)".

    1 unit * 20001cc -> overflow; the order stays PICKING.

    Design: Corner/errors/carton_overflow_when_fill_exceeds_large_inner_cc
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=20001, stock_qty=2,
                                          bin_capacity_cc=100000)
    order, wave = order_in_picking(client["id"], sku["id"], 1, ship_to_zone=2)
    resp = api.pack_order(client["id"], order["id"], {"cartons": [{"packed_units": 1}]},
                          TEST_USERS["pack_station_headers"])
    validate_error(resp, ApiErrorId.ERR_CARTON_OVERFLOW.value)
    refreshed = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed["status"] == "PICKING"


def test_cycle_count_to_zero_floors_quantities(api):
    """PRD §3.10: "the server reads the lot's `on_hand_qty` at apply time as the
    before-count baseline and records the count's `variance_qty` as the
    `counted_qty` minus that baseline; the variance may be negative."
    PRD §3.10: "The correction then sets the lot's `on_hand_qty` to `counted_qty`
    while conserving reserved units: the lot's `available_qty` becomes the larger
    of zero and `counted_qty` minus the lot's `reserved_qty`, so reserved units are
    protected first."

    Counting an 8-on-hand/0-reserved lot to 0 -> variance -8, on_hand 0, available 0.

    Design: Difficulty/boundary_precision_check/cycle_count_to_zero_floors_available_and_on_hand
    """
    client, sku, b, lot = setup_lot_with_version(stock_qty=8, unit_volume_cc=400)
    cc = validate_success(
        api.create_cycle_count(
            client["id"],
            {"lot_id": lot["id"], "expected_lot_version": lot["version"], "counted_qty": 0},
            RECEIVING,
        ),
        expected_status=201,
    )
    assert cc["variance_qty"] == -8

    final_lot = get_lot(lot["id"])
    assert final_lot["on_hand_qty"] == 0
    assert final_lot["available_qty"] == 0


def test_cycle_count_to_zero_recomputes_bin_occupancy(api):
    """PRD §3.10: "Applying the correction increments the lot's `version` by one and
    recomputes the owning bin's `occupied_cc`."

    A second assertion on the zero-count boundary instance: counting the 8-unit lot
    (8*400 = 3200cc) down to 0 drives the bin's occupied_cc to 0 and bumps version.

    Design: Difficulty/boundary_precision_check/cycle_count_to_zero_floors_available_and_on_hand
    """
    client, sku, b, lot = setup_lot_with_version(stock_qty=8, unit_volume_cc=400)
    assert get_bin(b["id"])["occupied_cc"] == 3200
    validate_success(
        api.create_cycle_count(
            client["id"],
            {"lot_id": lot["id"], "expected_lot_version": lot["version"], "counted_qty": 0},
            RECEIVING,
        ),
        expected_status=201,
    )
    assert get_bin(b["id"])["occupied_cc"] == 0
    assert get_lot(lot["id"])["version"] == lot["version"] + 1


def test_putaway_exactly_at_capacity_succeeds(api):
    """PRD §2.7: "The boundary is inclusive: `occupied_cc` may reach `capacity_cc`
    exactly, and only a result strictly greater than `capacity_cc` is rejected,
    with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409)."

    5 units * 400cc = 2000cc into a 2000cc bin -> succeeds, occupied_cc 2000.

    Design: Corner/validations/capacity_boundary_putaway_exactly_at_capacity_succeeds
    """
    client, sku, b, rcpt = setup_received_receipt(expected_qty=5, unit_volume_cc=400,
                                                  bin_type="GENERAL", capacity_cc=2000)
    putaway = validate_success(api.putaway_receipt(client["id"], rcpt["id"], RECEIVING))
    assert putaway["status"] == "PUTAWAY"
    assert get_bin(b["id"])["occupied_cc"] == 2000


def _list(resp):
    return resp.json()["data"]

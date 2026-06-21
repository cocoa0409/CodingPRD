"""Cross-entity state guards, resource-overlap rejections, and business validations.

Covers cross_entity_state_dependency, resource_temporal_overlap, and
priority_pair_validation_conflict difficulty rules, plus the validation/error
corner instances. Precedence pairs use validate_error_is_one_of because the PRD
states each error's trigger but does not pin which fires first.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    stock_client_sku_bin,
    order_in_picking,
    release_single_line_order,
    confirm_all_picks,
    pack_order,
    buy_label,
    ship_order,
    setup_packed_order,
    setup_labelled_order,
    setup_shipped_order,
    setup_received_receipt,
    setup_pallet_with_client_a,
    putaway_units,
    create_client,
    create_sku,
    create_bin,
    create_order,
    order_line,
    get_bin,
    make_client_user_headers,
    TEST_USERS,
)

RECEIVING = TEST_USERS["receiving_clerk_headers"]
WAVE = TEST_USERS["wave_planner_headers"]
SHIP = TEST_USERS["ship_station_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
PACK = TEST_USERS["pack_station_headers"]


# --- cross_entity_state_dependency ---

def test_ship_packed_order_without_label_rejected(api):
    """PRD §3.8: "A `ShipStation` ships a packed order, which requires the order to
    be in `PACKED` status (else `ERR_ORDER_NOT_PACKED`) and a purchased label — a
    `LABELLED` `Shipment` for the order — to exist (else `ERR_LABEL_REQUIRED`)."

    A PACKED order with no shipment cannot ship.

    Design: Difficulty/cross_entity_state_dependency/order_ship_requires_labelled_shipment
    """
    client, sku, b, order, cartons = setup_packed_order(order_qty=2, carton_units=[2], ship_to_zone=2)
    resp = api.ship_order(client["id"], order["id"], SHIP)
    validate_error(resp, ApiErrorId.ERR_LABEL_REQUIRED.value)
    refreshed = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed["status"] == "PACKED"


def test_unlabelled_order_ship_makes_no_state_change(api):
    """PRD §2.8: "All cascades described for any single operation complete
    atomically within that one triggering request; a request that fails any
    precondition makes no partial change."

    A second assertion on the label-required instance: the rejected ship leaves the
    order's billed_handling_cents at 0 (no partial billing cascade fired).

    Design: Difficulty/cross_entity_state_dependency/order_ship_requires_labelled_shipment
    """
    client, sku, b, order, cartons = setup_packed_order(order_qty=2, carton_units=[2], ship_to_zone=2)
    resp = api.ship_order(client["id"], order["id"], SHIP)
    validate_error(resp, ApiErrorId.ERR_LABEL_REQUIRED.value)
    refreshed = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed["status"] == "PACKED"
    assert refreshed["billed_handling_cents"] == 0


def test_void_shipment_after_order_shipped_rejected(api):
    """PRD §3.7: "A `LABELLED` shipment may be voided while its order is still
    `PACKED`, moving `LABELLED` to `VOIDED` (this requires the shipment to be
    `LABELLED`, else `ERR_SHIPMENT_NOT_LABELLED`, and the order to be `PACKED`,
    else `ERR_ORDER_NOT_PACKED`)."

    Once the order is SHIPPED, voiding its still-LABELLED shipment is rejected.

    Design: Difficulty/cross_entity_state_dependency/shipment_void_requires_order_packed
    """
    client, sku, b, order, shipment = setup_shipped_order(
        order_qty=2, carton_units=[2], ship_to_zone=2, carrier_discount_bps=0,
    )
    resp = api.void_shipment(client["id"], shipment["id"], SHIP)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PACKED.value)
    refreshed = validate_success(api.get_shipment(shipment["id"], SHIP))
    assert refreshed["status"] == "LABELLED"


def test_void_shipment_while_order_packed_succeeds(api):
    """PRD §3.7: "A `LABELLED` shipment may be voided while its order is still
    `PACKED`, moving `LABELLED` to `VOIDED` (this requires the shipment to be
    `LABELLED`, else `ERR_SHIPMENT_NOT_LABELLED`, and the order to be `PACKED`,
    else `ERR_ORDER_NOT_PACKED`)."

    A second assertion on the void-precondition instance: with the order still
    PACKED the void is permitted and the shipment becomes VOIDED.

    Design: Difficulty/cross_entity_state_dependency/shipment_void_requires_order_packed
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=2, carton_units=[2], ship_to_zone=2, carrier_discount_bps=0,
    )
    voided = validate_success(api.void_shipment(client["id"], shipment["id"], SHIP))
    assert voided["status"] == "VOIDED"


# --- resource_temporal_overlap ---

def test_putaway_over_capacity_rejected(api):
    """PRD §2.7: "A putaway or a sellable-return restock must not push `occupied_cc`
    above the bin's `capacity_cc`. The boundary is inclusive: `occupied_cc` may
    reach `capacity_cc` exactly, and only a result strictly greater than
    `capacity_cc` is rejected, with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409)."

    Bin holds 2000cc (cap 4000); a second putaway of 6*400=2400cc -> 4400 > 4000.

    Design: Difficulty/resource_temporal_overlap/bin_aggregate_volume_capacity_overlap_rejects_putaway
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    b = create_bin(bin_type="GENERAL", capacity_cc=4000)
    putaway_units(client["id"], sku["id"], b["id"], 5)  # 2000cc

    # Second receipt of 6 units, advanced to RECEIVED.
    rcpt2 = validate_success(
        api.create_receipt(client["id"], {"sku_id": sku["id"], "bin_id": b["id"], "expected_qty": 6}, RECEIVING),
        expected_status=201,
    )
    validate_success(api.receive_receipt(client["id"], rcpt2["id"], {"received_qty": 6}, RECEIVING))

    resp = api.putaway_receipt(client["id"], rcpt2["id"], RECEIVING)
    validate_error(resp, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED.value)
    assert get_bin(b["id"])["occupied_cc"] == 2000
    refreshed = validate_success(api.get_client_receipt(client["id"], rcpt2["id"], RECEIVING))
    assert refreshed["status"] == "RECEIVED"


def test_putaway_at_capacity_boundary_inclusive_succeeds(api):
    """PRD §2.7: "The boundary is inclusive: `occupied_cc` may reach `capacity_cc`
    exactly, and only a result strictly greater than `capacity_cc` is rejected,
    with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409)."

    A second, complementary assertion on the capacity-overlap instance: filling a
    bin to exactly its capacity (2000cc into 2000cc) is admitted, isolating the
    strictly-over boundary that the rejection test exercises.

    Design: Difficulty/resource_temporal_overlap/bin_aggregate_volume_capacity_overlap_rejects_putaway
    """
    client, sku, b, rcpt = setup_received_receipt(expected_qty=5, unit_volume_cc=400,
                                                  bin_type="GENERAL", capacity_cc=2000)
    putaway = validate_success(api.putaway_receipt(client["id"], rcpt["id"], RECEIVING))
    assert putaway["status"] == "PUTAWAY"
    assert get_bin(b["id"])["occupied_cc"] == 2000


def test_pallet_putaway_other_client_rejected(api):
    """PRD §2.6: "Putting away or restocking one client's units into a `PALLET`
    bin that already holds at least one unit of a different client's inventory is
    rejected with `ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT` (HTTP 409), even when the
    bin still has volume to spare."

    Design: Difficulty/resource_temporal_overlap/pallet_exclusive_occupancy_overlap_rejects_other_client
    """
    clientA, clientB, skuA, skuB, pallet, rcptB = setup_pallet_with_client_a(qtyA=4, unit_volume_cc=400)
    resp = api.putaway_receipt(clientB["id"], rcptB["id"], RECEIVING)
    validate_error(resp, ApiErrorId.ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT.value)

    refreshed = validate_success(api.get_client_receipt(clientB["id"], rcptB["id"], RECEIVING))
    assert refreshed["status"] == "RECEIVED"
    assert get_bin(pallet["id"])["occupied_cc"] == 1600  # only client A's 4*400


def test_general_bin_commingling_two_clients_allowed(api):
    """PRD §2.6: "Bins whose `bin_type` is `GENERAL` are each-pick shelves that
    permit commingling and are exempt from this rule."

    A second, complementary assertion on the pallet-exclusivity instance: the same
    two-client scenario on a GENERAL bin is admitted, isolating that the rejection
    is specific to PALLET geometry.

    Design: Difficulty/resource_temporal_overlap/pallet_exclusive_occupancy_overlap_rejects_other_client
    """
    clientA = create_client(name="GenA")
    clientB = create_client(name="GenB")
    skuA = create_sku(clientA["id"], unit_volume_cc=400)
    skuB = create_sku(clientB["id"], unit_volume_cc=400)
    general = create_bin(bin_type="GENERAL", capacity_cc=100000)
    putaway_units(clientA["id"], skuA["id"], general["id"], 4)  # 1600cc

    rcptB = validate_success(
        api.create_receipt(clientB["id"], {"sku_id": skuB["id"], "bin_id": general["id"], "expected_qty": 4}, RECEIVING),
        expected_status=201,
    )
    validate_success(api.receive_receipt(clientB["id"], rcptB["id"], {"received_qty": 4}, RECEIVING))
    putaway = validate_success(api.putaway_receipt(clientB["id"], rcptB["id"], RECEIVING))
    assert putaway["status"] == "PUTAWAY"
    assert get_bin(general["id"])["occupied_cc"] == 3200  # both clients' 4*400 commingled


# --- priority_pair_validation_conflict (PRD does not pin precedence -> one_of) ---

def test_putaway_blocked_and_over_capacity_reports_a_guard_error(api):
    """PRD §2.7: "only a result strictly greater than `capacity_cc` is rejected,
    with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409). A bin's `status` is `OPEN` when
    created and may be moved to `BLOCKED`; a `BLOCKED` bin rejects putaway, pick
    confirmation, and sellable-return restock with `ERR_BIN_BLOCKED` (HTTP 409)."

    Both conditions hold (blocked AND over-capacity); the PRD states each error's
    trigger but does not commit to a precedence, so either guard error is faithful.

    Design: Difficulty/priority_pair_validation_conflict/putaway_bin_blocked_beats_capacity_exceeded
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=800)
    b = create_bin(bin_type="GENERAL", capacity_cc=1000)
    rcpt = validate_success(
        api.create_receipt(client["id"], {"sku_id": sku["id"], "bin_id": b["id"], "expected_qty": 10}, RECEIVING),
        expected_status=201,
    )
    validate_success(api.receive_receipt(client["id"], rcpt["id"], {"received_qty": 10}, RECEIVING))
    validate_success(api.block_bin(b["id"], RECEIVING))

    resp = api.putaway_receipt(client["id"], rcpt["id"], RECEIVING)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_BIN_BLOCKED.value,
        ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED.value,
    ])
    refreshed = validate_success(api.get_client_receipt(client["id"], rcpt["id"], RECEIVING))
    assert refreshed["status"] == "RECEIVED"


def test_putaway_into_blocked_bin_with_room_returns_bin_blocked(api):
    """PRD §2.7: "a `BLOCKED` bin rejects putaway, pick confirmation, and
    sellable-return restock with `ERR_BIN_BLOCKED` (HTTP 409)."

    A second, single-guard isolation on the blocked-vs-capacity instance: when only
    the BLOCKED guard can fire (the bin has ample capacity), the error is
    unambiguously ERR_BIN_BLOCKED.

    Design: Difficulty/priority_pair_validation_conflict/putaway_bin_blocked_beats_capacity_exceeded
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    b = create_bin(bin_type="GENERAL", capacity_cc=100000)  # ample capacity
    rcpt = validate_success(
        api.create_receipt(client["id"], {"sku_id": sku["id"], "bin_id": b["id"], "expected_qty": 3}, RECEIVING),
        expected_status=201,
    )
    validate_success(api.receive_receipt(client["id"], rcpt["id"], {"received_qty": 3}, RECEIVING))
    validate_success(api.block_bin(b["id"], RECEIVING))

    resp = api.putaway_receipt(client["id"], rcpt["id"], RECEIVING)
    validate_error(resp, ApiErrorId.ERR_BIN_BLOCKED.value)


def test_second_release_of_released_wave_reports_a_guard_error(api):
    """PRD §3.4: "Release requires the wave to be in `BUILDING` status (else
    `ERR_WAVE_NOT_BUILDING`) and to have at least one member order (else
    `ERR_WAVE_EMPTY`)."
    PRD §3.4: "If any line cannot be covered, the entire release is rejected with
    `ERR_INSUFFICIENT_INVENTORY` (HTTP 409) and nothing is reserved."

    A wave released once is RELEASED (not BUILDING) and its inventory is now
    reserved; the PRD states both error triggers but does not pin their precedence.

    Design: Difficulty/priority_pair_validation_conflict/wave_release_state_beats_insufficient_inventory
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=2)
    order, wave = release_single_line_order(client["id"], sku["id"], 2, ship_to_zone=2)

    resp = api.release_wave(client["id"], wave["id"], WAVE)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_WAVE_NOT_BUILDING.value,
        ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value,
    ])
    refreshed = validate_success(api.get_client_wave(client["id"], wave["id"], WAVE))
    assert refreshed["status"] == "RELEASED"


def test_second_release_leaves_member_order_unchanged(api):
    """PRD §2.8: "All cascades described for any single operation complete
    atomically within that one triggering request; a request that fails any
    precondition makes no partial change."

    A second assertion on the wave state-vs-inventory instance: the rejected second
    release makes no partial change — the member order stays in its post-first-release
    state (PICKING), and the guard error is one of the two PRD-stated triggers.

    Design: Difficulty/priority_pair_validation_conflict/wave_release_state_beats_insufficient_inventory
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=2)
    order, wave = release_single_line_order(client["id"], sku["id"], 2, ship_to_zone=2)
    assert order["status"] == "PICKING"

    resp = api.release_wave(client["id"], wave["id"], WAVE)
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_WAVE_NOT_BUILDING.value,
        ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value,
    ])
    refreshed_order = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed_order["status"] == "PICKING"


# --- validation / error corner instances ---

def test_receipt_on_suspended_client_rejected(api):
    """PRD §3.1: "A client may later be suspended by a `BillingClerk`, moving its
    `status` from `ACTIVE` to `SUSPENDED`. A `SUSPENDED` client rejects new
    receipts and new orders with `ERR_CLIENT_SUSPENDED` (HTTP 409); existing work
    already in flight is unaffected."

    Design: Corner/validations/receipt_on_suspended_client_rejected
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    b = create_bin(bin_type="GENERAL", capacity_cc=100000)
    validate_success(api.suspend_client(client["id"], BILLING))

    resp = api.create_receipt(client["id"], {"sku_id": sku["id"], "bin_id": b["id"], "expected_qty": 5}, RECEIVING)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED.value)


def test_receipt_on_discontinued_sku_rejected(api):
    """PRD §3.1: "A `ClientUser` may discontinue a SKU, moving its `status` to
    `DISCONTINUED`; a `DISCONTINUED` SKU rejects new receipts with
    `ERR_SKU_DISCONTINUED` (HTTP 409)."

    Design: Corner/validations/receipt_on_discontinued_sku_rejected
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    b = create_bin(bin_type="GENERAL", capacity_cc=100000)
    validate_success(api.discontinue_sku(client["id"], sku["id"], make_client_user_headers(client["id"])))

    resp = api.create_receipt(client["id"], {"sku_id": sku["id"], "bin_id": b["id"], "expected_qty": 5}, RECEIVING)
    validate_error(resp, ApiErrorId.ERR_SKU_DISCONTINUED.value)


def test_import_order_zone_out_of_range_rejected(api):
    """PRD §3.3: "Each line is an object naming a `sku_id` and a `qty` that must be
    strictly greater than 0, and at least one line is required; an empty `lines`
    array, a zone outside 1 through 8, or a non-positive line quantity is rejected
    as `ERR_INVALID_REQUEST`."

    Design: Corner/validations/import_order_invalid_zone_out_of_range_rejected
    """
    client = create_client()
    sku = create_sku(client["id"], unit_volume_cc=400)
    resp = api.create_order(client["id"],
                            {"ship_to_zone": 9, "lines": [{"sku_id": sku["id"], "qty": 1}]},
                            make_client_user_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_pack_units_not_summing_to_total_rejected(api):
    """PRD §3.6: "The submitted carton `packed_units` must sum exactly to the
    order's `total_units`, else `ERR_PACK_UNIT_MISMATCH` (HTTP 409)."

    A 3-unit order packed into cartons summing to 2 is rejected; order stays PICKING.

    Design: Corner/validations/pack_units_not_summing_to_total_rejected
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=3)
    order, wave = order_in_picking(client["id"], sku["id"], 3, ship_to_zone=2)
    resp = api.pack_order(client["id"], order["id"], {"cartons": [{"packed_units": 2}]}, PACK)
    validate_error(resp, ApiErrorId.ERR_PACK_UNIT_MISMATCH.value)
    refreshed = validate_success(api.get_client_order(client["id"], order["id"], BILLING))
    assert refreshed["status"] == "PICKING"


def test_order_referencing_other_clients_sku_rejected(api):
    """PRD §2.6: "When an operation references these across a client-scoped path,
    the referenced resources must all belong to the path's client: a SKU's
    `client_id`, a lot's `client_id`, and an order's `client_id` must match the
    path client, and a lot's `sku_id` must point to a SKU owned by that same
    client. Any mismatch is rejected with `ERR_CLIENT_OWNERSHIP_MISMATCH` (HTTP 409)."

    Design: Corner/validations/ownership_mismatch_sku_of_other_client_on_order_rejected
    """
    clientA = create_client(name="OwnA")
    clientB = create_client(name="OwnB")
    skuB = create_sku(clientB["id"], unit_volume_cc=400)
    resp = api.create_order(clientA["id"],
                            {"ship_to_zone": 2, "lines": [{"sku_id": skuB["id"], "qty": 1}]},
                            make_client_user_headers(clientA["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_OWNERSHIP_MISMATCH.value)


def test_return_qty_exceeds_shipped_rejected(api):
    """PRD §3.9: "names the returned `sku_id` (which must have been shipped on that
    order), a restock `bin_id` (used only if the unit is later graded sellable),
    and a `qty` that must be strictly greater than 0 and must not exceed the units
    shipped for that SKU on the order, else `ERR_RETURN_QTY_EXCEEDS_SHIPPED`
    (HTTP 409)."

    Design: Corner/errors/return_qty_exceeds_shipped_rejected
    """
    client, sku, b, order, shipment = setup_shipped_order(
        order_qty=2, carton_units=[2], ship_to_zone=2, carrier_discount_bps=0,
    )
    resp = api.create_return(client["id"],
                            {"order_id": order["id"], "sku_id": sku["id"], "bin_id": b["id"], "qty": 3},
                            TEST_USERS["returns_clerk_headers"])
    validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_SHIPPED.value)


def test_add_already_released_order_not_imported_rejected(api):
    """PRD §3.3: "The planner adds an order to a building wave by supplying its
    `order_id`; the order must be in `IMPORTED` status (else `ERR_ORDER_NOT_IMPORTED`)
    and the wave must be in `BUILDING` (else `ERR_WAVE_NOT_BUILDING`)."

    An order already RESERVED (its first wave was released) cannot be added to a
    second BUILDING wave.

    Design: Corner/errors/add_order_already_in_wave_not_imported_rejected
    """
    client, sku, b = stock_client_sku_bin(unit_volume_cc=400, stock_qty=5)
    order, wave1 = release_single_line_order(client["id"], sku["id"], 2, ship_to_zone=2)
    wave2 = validate_success(api.create_wave(client["id"], WAVE), expected_status=201)
    resp = api.add_order_to_wave(client["id"], wave2["id"], {"order_id": order["id"]}, WAVE)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_IMPORTED.value)

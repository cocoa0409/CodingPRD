"""Composite setup helpers for the 3PL fulfillment API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server with an empty DB before every
test). Fixtures use get_success_data() internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: ClientUser is entity_backed:Client, so every ownership-gated
call (SKU onboard, order import/cancel) uses make_client_user_headers(client_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_client_user_headers,
)
from . import factories as f


# --- Header shortcuts (opaque roles use shared constants) ---
BILLING = TEST_USERS["billing_clerk_headers"]
RECEIVING = TEST_USERS["receiving_clerk_headers"]
WAVE = TEST_USERS["wave_planner_headers"]
PICK = TEST_USERS["pick_operator_headers"]
PACK = TEST_USERS["pack_station_headers"]
SHIP = TEST_USERS["ship_station_headers"]
RETURNS = TEST_USERS["returns_clerk_headers"]


# =============================================================================
# Tier 1: Primitive creators
# =============================================================================

def create_client(**overrides) -> dict:
    """Onboard a client. Returns the created Client."""
    resp = api_client.create_client(f.create_client_payload(**overrides), BILLING)
    return get_success_data(resp)


def create_sku(client_id, **overrides) -> dict:
    """Onboard a SKU under a client (ownership-gated -> client_user headers)."""
    resp = api_client.create_sku(
        client_id, f.create_sku_payload(**overrides), make_client_user_headers(client_id)
    )
    return get_success_data(resp)


def create_bin(**overrides) -> dict:
    """Create a warehouse bin. Returns the created Bin."""
    resp = api_client.create_bin(f.create_bin_payload(**overrides), RECEIVING)
    return get_success_data(resp)


def create_order(client_id, lines, **overrides) -> dict:
    """Import an order (ownership-gated -> client_user headers)."""
    resp = api_client.create_order(
        client_id, f.create_order_payload(lines, **overrides), make_client_user_headers(client_id)
    )
    return get_success_data(resp)


# =============================================================================
# Tier 2: Inventory landing — putaway a known quantity into a bin
# =============================================================================

def putaway_units(client_id, sku_id, bin_id, qty) -> dict:
    """Announce -> receive -> putaway `qty` units of a SKU into a bin.
    Returns the resulting Receipt (in PUTAWAY status)."""
    rcpt = get_success_data(
        api_client.create_receipt(client_id, f.create_receipt_payload(sku_id, bin_id, expected_qty=qty), RECEIVING)
    )
    get_success_data(api_client.receive_receipt(client_id, rcpt["id"], {"received_qty": qty}, RECEIVING))
    putaway = get_success_data(api_client.putaway_receipt(client_id, rcpt["id"], RECEIVING))
    return putaway


def lot_for(client_id, sku_id, bin_id) -> dict:
    """Fetch the (single) InventoryLot for a (sku, bin) pair via the list endpoint."""
    data, _ = _paginated(api_client.list_inventory_lots(RECEIVING, params={"sku_id": sku_id, "bin_id": bin_id}))
    assert data, "Setup failed: expected an InventoryLot for the (sku, bin)"
    return data[0]


def lots_for_sku(sku_id) -> list:
    """Fetch all InventoryLots for a SKU (across bins)."""
    data, _ = _paginated(api_client.list_inventory_lots(RECEIVING, params={"sku_id": sku_id}))
    return data


def _paginated(resp):
    body = resp.json()
    return body["data"], body.get("meta", {})


# =============================================================================
# Tier 3: Order progression through the pick/pack/ship pipeline
# =============================================================================

def stock_client_sku_bin(unit_volume_cc=400, hazmat=False, stock_qty=10,
                         bin_type="GENERAL", bin_capacity_cc=100000, **client_overrides):
    """Onboard a client + one SKU, create one bin, and putaway `stock_qty` units.
    Returns (client, sku, bin)."""
    client = create_client(**client_overrides)
    sku = create_sku(client["id"], unit_volume_cc=unit_volume_cc, hazmat=hazmat)
    b = create_bin(bin_type=bin_type, capacity_cc=bin_capacity_cc)
    if stock_qty > 0:
        putaway_units(client["id"], sku["id"], b["id"], stock_qty)
    return client, sku, b


def release_single_line_order(client_id, sku_id, qty, ship_to_zone=2):
    """Import a single-line order, add it to a fresh wave, and release the wave.
    Returns (order, wave). The order ends in PICKING with one ASSIGNED PickTask."""
    order = create_order(client_id, [f.order_line(sku_id, qty)], ship_to_zone=ship_to_zone)
    wave = get_success_data(api_client.create_wave(client_id, WAVE))
    get_success_data(api_client.add_order_to_wave(client_id, wave["id"], {"order_id": order["id"]}, WAVE))
    get_success_data(api_client.release_wave(client_id, wave["id"], WAVE))
    order = get_success_data(api_client.get_client_order(client_id, order["id"], WAVE))
    return order, wave


def pick_tasks_for_order(order_id) -> list:
    data, _ = _paginated(api_client.list_pick_tasks(WAVE, params={"order_id": order_id}))
    return data


def confirm_all_picks(client_id, order_id, picked_qty=None):
    """Confirm every ASSIGNED pick task for the order to its full qty (or `picked_qty`)."""
    for pt in pick_tasks_for_order(order_id):
        if pt["status"] != "ASSIGNED":
            continue
        q = pt["qty"] if picked_qty is None else picked_qty
        get_success_data(api_client.confirm_pick(client_id, pt["id"], {"picked_qty": q}, PICK))


def order_in_picking(client_id, sku_id, qty, ship_to_zone=2, stock_qty=None):
    """Reach an order in PICKING with all picks confirmed (ready to pack).
    Caller must have already stocked the bin (use stock_client_sku_bin)."""
    order, wave = release_single_line_order(client_id, sku_id, qty, ship_to_zone=ship_to_zone)
    confirm_all_picks(client_id, order["id"])
    return order, wave


def pack_order(client_id, order_id, carton_units):
    """Pack an order in PICKING into cartons. `carton_units` is a list of int
    packed_units per carton. Returns the updated Order (PACKED)."""
    cartons = [f.carton_entry(u) for u in carton_units]
    return get_success_data(api_client.pack_order(client_id, order_id, {"cartons": cartons}, PACK))


def cartons_for_order(order_id) -> list:
    data, _ = _paginated(api_client.list_cartons(PACK, params={"order_id": order_id}))
    return data


def buy_label(client_id, order_id, **payload_overrides):
    """Rate-shop and purchase a label for a PACKED order. Returns the Shipment."""
    payload = {"order_id": order_id}
    payload.update(payload_overrides)
    return get_success_data(api_client.create_shipment(client_id, payload, SHIP))


def ship_order(client_id, order_id):
    """Ship a PACKED order that already has a LABELLED shipment. Returns the Order (SHIPPED)."""
    return get_success_data(api_client.ship_order(client_id, order_id, SHIP))


# =============================================================================
# Tier 4: Full-lifecycle shortcuts (composite preambles)
# =============================================================================

def setup_packed_order(unit_volume_cc=400, hazmat=False, order_qty=2,
                       carton_units=None, ship_to_zone=2, stock_qty=None,
                       **client_overrides):
    """Build a client/sku/bin, stock it, import a single-line order, release,
    confirm picks, and pack. Returns (client, sku, bin, order, cartons).
    `carton_units` defaults to [order_qty] (one carton)."""
    if stock_qty is None:
        stock_qty = order_qty
    if carton_units is None:
        carton_units = [order_qty]
    client, sku, b = stock_client_sku_bin(
        unit_volume_cc=unit_volume_cc, hazmat=hazmat, stock_qty=stock_qty, **client_overrides
    )
    order, wave = order_in_picking(client["id"], sku["id"], order_qty, ship_to_zone=ship_to_zone)
    order = pack_order(client["id"], order["id"], carton_units)
    cartons = cartons_for_order(order["id"])
    return client, sku, b, order, cartons


def setup_labelled_order(unit_volume_cc=400, hazmat=False, order_qty=2,
                         carton_units=None, ship_to_zone=2, stock_qty=None,
                         shipment_overrides=None, **client_overrides):
    """A packed order that also has a LABELLED shipment (ready to ship).
    Returns (client, sku, bin, order, shipment)."""
    client, sku, b, order, _ = setup_packed_order(
        unit_volume_cc=unit_volume_cc, hazmat=hazmat, order_qty=order_qty,
        carton_units=carton_units, ship_to_zone=ship_to_zone, stock_qty=stock_qty,
        **client_overrides
    )
    shipment = buy_label(client["id"], order["id"], **(shipment_overrides or {}))
    return client, sku, b, order, shipment


def setup_shipped_order(unit_volume_cc=400, hazmat=False, order_qty=2,
                        carton_units=None, ship_to_zone=2, stock_qty=None,
                        **client_overrides):
    """A fully shipped order (carton SHIPPED, inventory consumed, handling billed).
    Returns (client, sku, bin, order, shipment)."""
    client, sku, b, order, shipment = setup_labelled_order(
        unit_volume_cc=unit_volume_cc, hazmat=hazmat, order_qty=order_qty,
        carton_units=carton_units, ship_to_zone=ship_to_zone, stock_qty=stock_qty,
        **client_overrides
    )
    order = ship_order(client["id"], order["id"])
    return client, sku, b, order, shipment


# =============================================================================
# Tier 5: Specialised threshold / accumulation fixtures
# =============================================================================

def setup_lot_with_version(stock_qty=8, unit_volume_cc=400, **client_overrides):
    """Putaway `stock_qty` units, then return (client, sku, bin, lot) where the
    lot carries its current version for OCC cycle-count tests."""
    client, sku, b = stock_client_sku_bin(
        unit_volume_cc=unit_volume_cc, stock_qty=stock_qty, **client_overrides
    )
    lot = lot_for(client["id"], sku["id"], b["id"])
    return client, sku, b, lot


def setup_pallet_with_client_a(qtyA=4, unit_volume_cc=400, capacity_cc=100000):
    """Create two clients (A, B), a shared PALLET bin holding client A's units,
    and a RECEIVED receipt for client B targeting the same PALLET bin (not yet
    putaway). Returns (clientA, clientB, skuA, skuB, bin, receiptB)."""
    clientA = create_client(name="ClientA")
    clientB = create_client(name="ClientB")
    skuA = create_sku(clientA["id"], unit_volume_cc=unit_volume_cc)
    skuB = create_sku(clientB["id"], unit_volume_cc=unit_volume_cc)
    pallet = create_bin(bin_type="PALLET", capacity_cc=capacity_cc)
    putaway_units(clientA["id"], skuA["id"], pallet["id"], qtyA)
    rcptB = get_success_data(
        api_client.create_receipt(
            clientB["id"], f.create_receipt_payload(skuB["id"], pallet["id"], expected_qty=qtyA), RECEIVING
        )
    )
    get_success_data(api_client.receive_receipt(clientB["id"], rcptB["id"], {"received_qty": qtyA}, RECEIVING))
    return clientA, clientB, skuA, skuB, pallet, rcptB


def setup_received_receipt(expected_qty, unit_volume_cc=400, bin_type="GENERAL",
                           capacity_cc=100000, **client_overrides):
    """Build client/sku/bin and a receipt advanced to RECEIVED (not putaway).
    Returns (client, sku, bin, receipt)."""
    client = create_client(**client_overrides)
    sku = create_sku(client["id"], unit_volume_cc=unit_volume_cc)
    b = create_bin(bin_type=bin_type, capacity_cc=capacity_cc)
    rcpt = get_success_data(
        api_client.create_receipt(client["id"], f.create_receipt_payload(sku["id"], b["id"], expected_qty=expected_qty), RECEIVING)
    )
    # Capture the post-receive receipt (status RECEIVED, received_qty set) so the
    # returned object reflects the advanced state, not the announce-time snapshot.
    rcpt = get_success_data(
        api_client.receive_receipt(client["id"], rcpt["id"], {"received_qty": expected_qty}, RECEIVING)
    )
    return client, sku, b, rcpt


def get_client(client_id) -> dict:
    return get_success_data(api_client.get_client(client_id, BILLING))


def get_order(client_id, order_id) -> dict:
    return get_success_data(api_client.get_client_order(client_id, order_id, BILLING))


def get_bin(bin_id) -> dict:
    return get_success_data(api_client.get_bin(bin_id, RECEIVING))


def get_lot(lot_id) -> dict:
    return get_success_data(api_client.get_inventory_lot(lot_id, RECEIVING))


def get_pick_task(pick_task_id) -> dict:
    return get_success_data(api_client.get_pick_task(pick_task_id, WAVE))

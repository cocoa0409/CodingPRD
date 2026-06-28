"""Order endpoints and lifecycle (PRD §3.3, §3.5, §3.6, §3.8)."""
from flask import Blueprint, request

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_sku, get_order,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_order
import calc
from services import order_ops

bp = Blueprint("orders", __name__)

READ_ROLES_LIST = {"ClientUser", "WavePlanner", "BillingClerk", "ShipStation"}
READ_ROLES_GET = {"ClientUser", "WavePlanner", "BillingClerk", "ShipStation", "PackStation"}


def _filter_orders(items):
    for key in ("client_id", "wave_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    return items


@bp.route("/orders", methods=["GET"])
def list_orders():
    _, role = get_auth()
    require_roles(role, READ_ROLES_LIST)
    limit, offset = parse_pagination()
    items = _filter_orders(list(store.orders.values()))
    page, meta = paginate(items, limit, offset)
    return success([serialize_order(r) for r in page], pagination=meta)


@bp.route("/orders/<order_id>", methods=["GET"])
def get_one_order_flat(order_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES_GET)
    rec = get_order(order_id)
    return success(serialize_order(rec))


@bp.route("/clients/<client_id>/orders", methods=["POST"])
def import_order(client_id):
    _, role = get_auth()
    require_roles(role, {"ClientUser"})
    client = get_client(client_id)
    body = get_json_body()

    ship_to_zone = body.get("ship_to_zone")
    if isinstance(ship_to_zone, bool) or not isinstance(ship_to_zone, int):
        raise err("ERR_INVALID_REQUEST", "ship_to_zone must be an integer")
    if ship_to_zone < 1 or ship_to_zone > 8:
        raise err("ERR_INVALID_REQUEST", "ship_to_zone must be 1..8")

    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise err("ERR_INVALID_REQUEST", "lines must be a non-empty array")

    parsed_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_REQUEST", "each line must be an object")
        sku_id = line.get("sku_id")
        qty = line.get("qty")
        if not isinstance(sku_id, str) or sku_id == "":
            raise err("ERR_INVALID_REQUEST", "line.sku_id is required")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err("ERR_INVALID_REQUEST", "line.qty must be an integer")
        if qty <= 0:
            raise err("ERR_INVALID_REQUEST", "line.qty must be > 0")
        parsed_lines.append({"sku_id": sku_id, "qty": qty})

    # FK existence + cross-ownership for each line SKU.
    for line in parsed_lines:
        sku = get_sku(line["sku_id"])
        if sku["client_id"] != client_id:
            raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "SKU not owned by path client")

    if client["status"] == "SUSPENDED":
        raise err("ERR_CLIENT_SUSPENDED", "Client is suspended")

    rec = stamp_create({
        "id": new_id(),
        "client_id": client_id,
        "wave_id": None,
        "ship_to_zone": ship_to_zone,
        "lines": parsed_lines,
        "estimated_handling_cents": 0,
        "billed_handling_cents": 0,
        "status": "IMPORTED",
    })
    store.orders[rec["id"]] = rec
    return success(serialize_order(rec), status=201)


@bp.route("/clients/<client_id>/orders", methods=["GET"])
def list_client_orders(client_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES_LIST)
    get_client(client_id)
    limit, offset = parse_pagination()
    items = [o for o in store.orders.values() if o["client_id"] == client_id]
    wave_id = request.args.get("wave_id")
    if wave_id is not None:
        items = [o for o in items if o.get("wave_id") == wave_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize_order(r) for r in page], pagination=meta)


def _resolve_order(client_id, order_id):
    get_client(client_id)
    rec = get_order(order_id)
    if rec["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Order not owned by path client")
    return rec


@bp.route("/clients/<client_id>/orders/<order_id>", methods=["GET"])
def get_client_order(client_id, order_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES_GET)
    rec = _resolve_order(client_id, order_id)
    return success(serialize_order(rec))


@bp.route("/clients/<client_id>/orders/<order_id>/pack", methods=["POST"])
def pack_order(client_id, order_id):
    _, role = get_auth()
    require_roles(role, {"PackStation"})
    order = _resolve_order(client_id, order_id)
    body = get_json_body()

    if order["status"] != "PICKING":
        raise err("ERR_ORDER_NOT_PICKING", "Order is not PICKING")

    pick_tasks = order_ops.pick_tasks_for_order(order_id)
    if any(pt["status"] != "PICKED" for pt in pick_tasks):
        raise err("ERR_PICKS_INCOMPLETE", "Not every pick task is PICKED")

    cartons = body.get("cartons")
    if not isinstance(cartons, list) or len(cartons) == 0:
        raise err("ERR_INVALID_REQUEST", "cartons must be a non-empty array")

    total_units = order_ops.order_total_units(order)

    # Validate each carton's packed_units; sum must equal total_units.
    parsed = []
    running = 0
    for c in cartons:
        if not isinstance(c, dict):
            raise err("ERR_INVALID_REQUEST", "each carton must be an object")
        packed_units = c.get("packed_units")
        if isinstance(packed_units, bool) or not isinstance(packed_units, int):
            raise err("ERR_INVALID_REQUEST", "packed_units must be an integer")
        if packed_units <= 0:
            raise err("ERR_INVALID_REQUEST", "packed_units must be > 0")
        running += packed_units
        if running > total_units:
            raise err("ERR_PACK_UNIT_MISMATCH", "packed_units exceed remaining unpacked picked units")
        parsed.append(packed_units)

    if running != total_units:
        raise err("ERR_PACK_UNIT_MISMATCH", "Submitted packed_units do not sum to total_units")

    # Build a flat list of unit volumes in line order, then assign units to cartons
    # sequentially so each carton's fill_volume_cc is the sum of its units' volumes.
    unit_volumes = []
    for line in order["lines"]:
        sku = store.skus.get(line["sku_id"])
        vol = sku["unit_volume_cc"] if sku else 0
        unit_volumes.extend([vol] * line["qty"])

    # First pass: compute fill volumes and validate no carton overflows LARGE,
    # so a failure makes no partial change (atomicity, PRD §2.8).
    idx = 0
    computed = []
    for packed_units in parsed:
        fill = sum(unit_volumes[idx:idx + packed_units])
        idx += packed_units
        size = calc.cartonization_size(fill)
        if size is None:
            raise err("ERR_CARTON_OVERFLOW", "Carton fill exceeds LARGE box")
        computed.append((packed_units, fill, size))

    # Commit cartons.
    for packed_units, fill, size in computed:
        carton = stamp_create({
            "id": new_id(),
            "order_id": order_id,
            "packed_units": packed_units,
            "fill_volume_cc": fill,
            "carton_size": size,
            "status": "PACKED",
        })
        store.cartons[carton["id"]] = carton

    # Stamp estimated handling (unit-only basis, no carton surcharge).
    order["estimated_handling_cents"] = calc.estimated_handling_cents(store.clients[client_id], total_units)
    order["status"] = "PACKED"
    touch(order)
    return success(serialize_order(order))


@bp.route("/clients/<client_id>/orders/<order_id>/ship", methods=["POST"])
def ship_order(client_id, order_id):
    _, role = get_auth()
    require_roles(role, {"ShipStation"})
    order = _resolve_order(client_id, order_id)

    if order["status"] != "PACKED":
        raise err("ERR_ORDER_NOT_PACKED", "Order is not PACKED")

    # A purchased label (LABELLED shipment) must exist for the order.
    labelled = [
        s for s in store.shipments.values()
        if s["order_id"] == order_id and s["status"] == "LABELLED"
    ]
    if not labelled:
        raise err("ERR_LABEL_REQUIRED", "No purchased label for this order")

    # Consume reservations: reserved -= qty AND on_hand -= qty.
    order_ops.consume_reservations(order)

    # All cartons PACKED -> SHIPPED.
    for carton in order_ops.cartons_for_order(order_id, statuses={"PACKED"}):
        carton["status"] = "SHIPPED"
        touch(carton)

    # Billed handling = base + unit_component + carton surcharge.
    carton_count = len(order_ops.cartons_for_order(order_id))
    client = store.clients[client_id]
    total_units = order_ops.order_total_units(order)
    billed = calc.billed_handling_cents(client, total_units, carton_count)
    order["billed_handling_cents"] = billed

    # Post a HANDLING BillingCharge; credit client handling_balance.
    from db import stamp_create_charge
    charge = stamp_create_charge({
        "id": new_id(),
        "client_id": client_id,
        "charge_type": "HANDLING",
        "amount_cents": billed,
        "source_order_id": order_id,
        "posted": True,
    })
    store.billing_charges[charge["id"]] = charge
    client["handling_balance_cents"] += billed
    touch(client)

    wave_id = order["wave_id"]
    order["status"] = "SHIPPED"
    touch(order)

    order_ops.maybe_complete_wave(wave_id)
    return success(serialize_order(order))


@bp.route("/clients/<client_id>/orders/<order_id>/short", methods=["POST"])
def short_order(client_id, order_id):
    _, role = get_auth()
    require_roles(role, {"PickOperator"})
    order = _resolve_order(client_id, order_id)

    if order["status"] != "PICKING":
        raise err("ERR_ORDER_NOT_PICKING", "Order is not PICKING")

    pick_tasks = order_ops.pick_tasks_for_order(order_id)
    if not any(pt["picked_qty"] < pt["qty"] for pt in pick_tasks):
        raise err("ERR_NOT_SHORT", "No pick task is under-picked")

    order_ops.release_reservations_short(order)

    wave_id = order["wave_id"]
    order["status"] = "SHORT"
    touch(order)

    order_ops.maybe_complete_wave(wave_id)
    return success(serialize_order(order))


@bp.route("/clients/<client_id>/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(client_id, order_id):
    _, role = get_auth()
    require_roles(role, {"ClientUser"})
    order = _resolve_order(client_id, order_id)

    if order["status"] not in {"IMPORTED", "RESERVED"}:
        raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is not cancellable")

    wave_id = order["wave_id"]

    if order["status"] == "RESERVED":
        order_ops.release_reservations_cancel(order)

    # Detach from wave (both IMPORTED and RESERVED).
    if order["wave_id"] is not None:
        order["wave_id"] = None

    order["status"] = "CANCELLED"
    touch(order)

    order_ops.maybe_complete_wave(wave_id)
    return success(serialize_order(order))

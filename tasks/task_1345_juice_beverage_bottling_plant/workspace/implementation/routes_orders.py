"""ShipmentOrder endpoints: place, allocate (FEFO), pick, ship, cancel."""
from flask import Blueprint, request

from domain import (CHANNELS, MIN_SHELF_LIFE, UNITS_PER_PALLET, ceil_div,
                    effective_expiry, order_pallet_count, ser_order)
from errors import err
from routes_customers import get_customer_or_404
from routes_formulas import get_formula_or_404
from services import post_pallet_entry
from store import db, stamp, touch
from util import body, ok, paginate, req_enum, req_field, require_any, require_roles

bp = Blueprint("orders", __name__)


def get_order_or_404(order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise err("ERR_SHIPMENT_ORDER_NOT_FOUND", f"ShipmentOrder {order_id} not found")
    return order


@bp.post("/v1/shipment-orders")
def create_order():
    user_id, role = require_roles("CustomerServiceRep", "CustomerContact")
    data = body()
    customer_id = data.get("customer_id")
    if role == "CustomerContact" and customer_id is not None and customer_id != user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "CustomerContact may only act on its own customer account")
    customer_id = req_field(data, "customer_id", "str")
    formula_id = req_field(data, "formula_id", "str")
    channel = req_enum(data, "channel", CHANNELS)
    delivery_date = req_field(data, "requested_delivery_date", "date")
    units_requested = req_field(data, "units_requested", "int")
    customer = get_customer_or_404(customer_id)
    formula = get_formula_or_404(formula_id)
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_NOT_ACTIVE", "Customer must be ACTIVE to place an order")
    if formula["customer_id"] != customer_id:
        raise err("ERR_FORMULA_CUSTOMER_MISMATCH",
                  "The formula does not belong to this customer")
    if delivery_date < db.clock.date():
        raise err("ERR_DELIVERY_DATE_IN_PAST",
                  "requested_delivery_date precedes the current logical date")
    order = {
        "customer_id": customer_id,
        "formula_id": formula_id,
        "channel": channel,
        "requested_delivery_date": delivery_date.isoformat(),
        "_requested_delivery_date": delivery_date,
        "units_requested": units_requested,
        "min_shelf_life_days": MIN_SHELF_LIFE[channel],
        "allocations": [],
        "status": "PLACED",
    }
    stamp(order)
    db.orders[order["id"]] = order
    return ok(ser_order(order), 201)


@bp.get("/v1/shipment-orders")
def list_orders():
    require_any()
    customer_id = request.args.get("customer_id")
    formula_id = request.args.get("formula_id")
    status = request.args.get("status")
    items = list(db.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if formula_id is not None:
        items = [o for o in items if o["formula_id"] == formula_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginate(items, ser_order)


@bp.get("/v1/shipment-orders/<order_id>")
def get_order(order_id):
    require_any()
    return ok(ser_order(get_order_or_404(order_id)))


@bp.post("/v1/shipment-orders/<order_id>/allocate")
def allocate_order(order_id):
    require_roles("WarehouseLead")
    order = get_order_or_404(order_id)
    data = body()
    expected = req_field(data, "expected_shipment_order_version", "int")
    if expected != order["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_shipment_order_version does not match the order's current version")
    if order["status"] not in ("PLACED", "BACKORDERED"):
        raise err("ERR_ORDER_STATE_INVALID", "allocate requires status PLACED or BACKORDERED")
    customer = get_customer_or_404(order["customer_id"])
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_NOT_ACTIVE", "Customer must be ACTIVE to allocate an order")
    # FEFO waterfall over the eligible pool; existing allocations are kept.
    delivery = order["_requested_delivery_date"]
    minimum = order["min_shelf_life_days"]
    eligible = []
    for lot in db.fg_lots.values():
        if lot["formula_id"] != order["formula_id"] or lot["customer_id"] != order["customer_id"]:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        lot_available = lot["units_total"] - lot["units_allocated"] - lot["units_shipped"]
        if lot_available <= 0:
            continue
        expiry = effective_expiry(lot, order["channel"])
        if (expiry - delivery).days < minimum:
            continue
        eligible.append((expiry, lot["created_at"], lot["_seq"], lot))
    eligible.sort(key=lambda t: (t[0], t[1], t[2]))
    remaining = order["units_requested"] - sum(a["units"] for a in order["allocations"])
    for _, _, _, lot in eligible:
        if remaining <= 0:
            break
        lot_available = lot["units_total"] - lot["units_allocated"] - lot["units_shipped"]
        take = min(lot_available, remaining)
        if take <= 0:
            continue
        existing = next((a for a in order["allocations"] if a["lot_id"] == lot["id"]), None)
        if existing is not None:
            existing["units"] += take
        else:
            order["allocations"].append({"lot_id": lot["id"], "units": take})
        lot["units_allocated"] += take
        touch(lot)
        remaining -= take
    allocated = sum(a["units"] for a in order["allocations"])
    order["status"] = "ALLOCATED" if allocated == order["units_requested"] else "BACKORDERED"
    touch(order)
    return ok(ser_order(order))


@bp.post("/v1/shipment-orders/<order_id>/pick")
def pick_order(order_id):
    require_roles("WarehouseLead")
    order = get_order_or_404(order_id)
    if order["status"] != "ALLOCATED":
        raise err("ERR_ORDER_STATE_INVALID", "pick requires status ALLOCATED")
    order["status"] = "PICKED"
    touch(order)
    return ok(ser_order(order))


@bp.post("/v1/shipment-orders/<order_id>/ship")
def ship_order(order_id):
    require_roles("WarehouseLead")
    order = get_order_or_404(order_id)
    if order["status"] != "PICKED":
        raise err("ERR_ORDER_STATE_INVALID", "ship requires status PICKED")
    for alloc in order["allocations"]:
        lot = db.fg_lots.get(alloc["lot_id"])
        if lot is None or lot["status"] != "AVAILABLE":
            raise err("ERR_ORDER_CONTAINS_UNSHIPPABLE_LOT",
                      "An allocated lot is no longer AVAILABLE")
    for alloc in order["allocations"]:
        lot = db.fg_lots[alloc["lot_id"]]
        lot["units_shipped"] += alloc["units"]
        lot["units_allocated"] -= alloc["units"]
        if lot["units_total"] - lot["units_shipped"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
    order["status"] = "SHIPPED"
    touch(order)
    # pallet escrow posting
    account = None
    for a in db.pallet_accounts.values():
        if a["customer_id"] == order["customer_id"]:
            account = a
            break
    if account is not None:
        pallets = order_pallet_count(order)
        if pallets > 0:
            post_pallet_entry(account, "SHIP", pallets, shipment_order_id=order["id"])
            customer = get_customer_or_404(order["customer_id"])
            customer["outstanding_balance_cents"] += pallets * customer["pallet_deposit_cents"]
            touch(customer)
    return ok(ser_order(order))


@bp.post("/v1/shipment-orders/<order_id>/cancel")
def cancel_order(order_id):
    require_roles("WarehouseLead", "CustomerServiceRep")
    order = get_order_or_404(order_id)
    if order["status"] not in ("PLACED", "BACKORDERED", "ALLOCATED", "PICKED"):
        raise err("ERR_ORDER_STATE_INVALID",
                  "cancel requires status PLACED, BACKORDERED, ALLOCATED or PICKED")
    for alloc in order["allocations"]:
        lot = db.fg_lots.get(alloc["lot_id"])
        if lot is not None:
            lot["units_allocated"] -= alloc["units"]
            touch(lot)
    order["allocations"] = []
    order["status"] = "CANCELLED"
    touch(order)
    return ok(ser_order(order))

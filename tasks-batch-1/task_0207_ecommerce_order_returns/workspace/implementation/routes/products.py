"""Product + product-scoped listing endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import err, ERR_VALIDATION
from middleware import require_roles, get_auth
from response import success
from services import serialize
from services.common import (
    parse_body, require_str, require_int, optional_int, optional_bool,
    paginate, lookup,
)

bp = Blueprint("products", __name__)


@bp.route("/products", methods=["POST"])
def create_product():
    require_roles(["StoreAdmin"])
    body = parse_body()
    sku = require_str(body, "sku")
    title = require_str(body, "title")
    unit_price = require_int(body, "unit_price_cents")
    if unit_price < 0:
        raise err(ERR_VALIDATION, "unit_price_cents must be >= 0")
    tax_rate = require_int(body, "tax_rate_bps")
    if tax_rate < 0:
        raise err(ERR_VALIDATION, "tax_rate_bps must be >= 0")
    restocking_fee = optional_int(body, "restocking_fee_bps", 0)
    if restocking_fee < 0 or restocking_fee > 10000:
        raise err(ERR_VALIDATION, "restocking_fee_bps must be within 0..10000")
    return_window = require_int(body, "return_window_days")
    if return_window < 0:
        raise err(ERR_VALIDATION, "return_window_days must be >= 0")
    final_sale = optional_bool(body, "final_sale", False)
    for p in db.products.values():
        if p["sku"] == sku:
            raise err(ERR_VALIDATION, "sku already exists")
    rec = {
        "sku": sku,
        "title": title,
        "unit_price_cents": unit_price,
        "tax_rate_bps": tax_rate,
        "restocking_fee_bps": restocking_fee,
        "return_window_days": return_window,
        "final_sale": final_sale,
    }
    db.stamp_create(rec)
    db.products[rec["id"]] = rec
    return success(serialize.product(rec), status=201)


@bp.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    # Authorized roles: Anonymous, Customer, StoreAdmin, WarehouseOperator.
    # Any authenticated known role passes; Anonymous is one of the four roles
    # so a present, known X-User-Role header is still required.
    require_roles(["Anonymous", "Customer", "StoreAdmin", "WarehouseOperator"])
    rec = lookup(db.products, pid)
    return success(serialize.product(rec))


@bp.route("/products/<pid>/inventory", methods=["GET"])
def list_product_inventory(pid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.products, pid)
    rows = [i for i in db.inventory_items.values() if i["product_id"] == pid]
    data, meta = paginate(rows, serialize.inventory_item)
    return success(data, pagination=meta)


@bp.route("/products/<pid>/reservations", methods=["GET"])
def list_product_reservations(pid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.products, pid)
    rows = [r for r in db.reservations.values() if r["product_id"] == pid]
    data, meta = paginate(rows, serialize.reservation)
    return success(data, pagination=meta)


@bp.route("/products/<pid>/order-lines", methods=["GET"])
def list_product_order_lines(pid):
    require_roles(["StoreAdmin"])
    lookup(db.products, pid)
    rows = [l for l in db.order_lines.values() if l["product_id"] == pid]
    data, meta = paginate(rows, serialize.order_line)
    return success(data, pagination=meta)


@bp.route("/products/<pid>/return-lines", methods=["GET"])
def list_product_return_lines(pid):
    require_roles(["StoreAdmin"])
    lookup(db.products, pid)
    rows = [rl for rl in db.return_lines.values() if rl.get("exchange_product_id") == pid]
    data, meta = paginate(rows, serialize.return_line)
    return success(data, pagination=meta)


# ----- inventory items (top-level) -----

@bp.route("/inventory", methods=["POST"])
def create_inventory():
    require_roles(["StoreAdmin", "WarehouseOperator"])
    body = parse_body()
    product_id = require_str(body, "product_id")
    warehouse_id = require_str(body, "warehouse_id")
    on_hand = require_int(body, "on_hand_qty")
    if on_hand < 0:
        raise err(ERR_VALIDATION, "on_hand_qty must be >= 0")
    # existence of body FKs
    lookup(db.products, product_id)
    lookup(db.warehouses, warehouse_id)
    rec = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "on_hand_qty": on_hand,
    }
    db.stamp_create(rec)
    db.inventory_items[rec["id"]] = rec
    return success(serialize.inventory_item(rec), status=201)


@bp.route("/inventory/<iid>", methods=["GET"])
def get_inventory(iid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    rec = lookup(db.inventory_items, iid)
    return success(serialize.inventory_item(rec))


@bp.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    rec = lookup(db.reservations, rid)
    return success(serialize.reservation(rec))


@bp.route("/reservations/<rid>/shipment-lines", methods=["GET"])
def list_reservation_shipment_lines(rid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.reservations, rid)
    rows = [sl for sl in db.shipment_lines.values() if sl["reservation_id"] == rid]
    data, meta = paginate(rows, serialize.shipment_line)
    return success(data, pagination=meta)

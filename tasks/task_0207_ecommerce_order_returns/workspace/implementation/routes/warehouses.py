"""Warehouse + warehouse-scoped listing endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import err, ERR_VALIDATION
from middleware import require_roles
from response import success
from services import serialize
from services.common import (
    parse_body, require_str, require_int, optional_bool, paginate, lookup,
)

bp = Blueprint("warehouses", __name__)


@bp.route("/warehouses", methods=["POST"])
def create_warehouse():
    require_roles(["StoreAdmin"])
    body = parse_body()
    code = require_str(body, "code")
    name = require_str(body, "name")
    priority = require_int(body, "fulfillment_priority")
    if priority < 1:
        raise err(ERR_VALIDATION, "fulfillment_priority must be >= 1")
    accepts_returns = optional_bool(body, "accepts_returns", True)
    for w in db.warehouses.values():
        if w["code"] == code:
            raise err(ERR_VALIDATION, "warehouse code already exists")
    rec = {
        "code": code,
        "name": name,
        "fulfillment_priority": priority,
        "accepts_returns": accepts_returns,
    }
    db.stamp_create(rec)
    db.warehouses[rec["id"]] = rec
    return success(serialize.warehouse(rec), status=201)


@bp.route("/warehouses/<wid>", methods=["GET"])
def get_warehouse(wid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    rec = lookup(db.warehouses, wid)
    return success(serialize.warehouse(rec))


@bp.route("/warehouses/<wid>/inventory", methods=["GET"])
def list_warehouse_inventory(wid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.warehouses, wid)
    rows = [i for i in db.inventory_items.values() if i["warehouse_id"] == wid]
    data, meta = paginate(rows, serialize.inventory_item)
    return success(data, pagination=meta)


@bp.route("/warehouses/<wid>/shipments", methods=["GET"])
def list_warehouse_shipments(wid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.warehouses, wid)
    rows = [s for s in db.shipments.values() if s["warehouse_id"] == wid]
    data, meta = paginate(rows, serialize.shipment)
    return success(data, pagination=meta)


@bp.route("/warehouses/<wid>/reservations", methods=["GET"])
def list_warehouse_reservations(wid):
    require_roles(["StoreAdmin", "WarehouseOperator"])
    lookup(db.warehouses, wid)
    rows = [r for r in db.reservations.values() if r["warehouse_id"] == wid]
    data, meta = paginate(rows, serialize.reservation)
    return success(data, pagination=meta)

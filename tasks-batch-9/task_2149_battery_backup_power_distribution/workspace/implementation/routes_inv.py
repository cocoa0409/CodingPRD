"""Inventory lots: receiving, refresh charging and scrapping."""
from datetime import timedelta

from flask import Blueprint

import calc
from common import (
    ApiError, DB, D, authenticate, f_date, f_int, f_num, f_str, get_body, must,
    new_row, now_ts, ok, page, parse_dt, public, qp, touch,
)

bp = Blueprint("inventory", __name__, url_prefix="/distribution")

LOT_READERS = ["PlatformAdmin", "SalesRep", "WarehouseOperator", "ComplianceOfficer"]


@bp.post("/inventory-lots")
def receive_lot():
    authenticate(["PlatformAdmin", "WarehouseOperator"])
    body = get_body()
    model_id = f_str(body, "battery_model_id")
    warehouse_id = f_str(body, "warehouse_id")
    manufactured_on = f_date(body, "manufactured_on")
    quantity = f_int(body, "quantity_on_hand", minimum=0)
    must("battery_models", model_id)
    must("warehouses", warehouse_id)
    row = new_row({
        "battery_model_id": model_id,
        "warehouse_id": warehouse_id,
        "manufactured_on": manufactured_on,
        "quantity_on_hand": quantity,
        "quantity_reserved": 0,
        "quantity_available": quantity,
        "last_refresh_charged_at": None,
        "refresh_charge_count": 0,
        "last_measured_open_circuit_voltage": None,
        "state_of_charge_pct": 100.0,
        "condition_state": "SELLABLE",
        "scrap_manifest_id": None,
    })
    DB.inventory_lots[row["id"]] = row
    return ok(calc.serialize_lot(row), 201)


@bp.get("/inventory-lots/<lot_id>")
def read_lot(lot_id):
    authenticate(LOT_READERS)
    return ok(calc.serialize_lot(must("inventory_lots", lot_id)))


@bp.get("/inventory-lots")
def list_lots():
    authenticate(LOT_READERS)
    rows = list(DB.inventory_lots.values())
    for row in rows:
        calc.lot_view(row)
    model_id = qp("battery_model_id")
    warehouse_id = qp("warehouse_id")
    manifest_id = qp("scrap_manifest_id")
    condition = qp("condition_state")
    if model_id is not None:
        rows = [r for r in rows if r["battery_model_id"] == model_id]
    if warehouse_id is not None:
        rows = [r for r in rows if r["warehouse_id"] == warehouse_id]
    if manifest_id is not None:
        rows = [r for r in rows if r["scrap_manifest_id"] == manifest_id]
    if condition is not None:
        rows = [r for r in rows if r["condition_state"] == condition]
    return page(rows, calc.serialize_lot)


@bp.post("/inventory-lots/<lot_id>/refresh-charge")
def refresh_charge(lot_id):
    authenticate(["WarehouseOperator"])
    lot = must("inventory_lots", lot_id)
    body = get_body()
    voltage = f_num(body, "measured_open_circuit_voltage")

    calc.lot_view(lot)
    if lot["condition_state"] not in ("SELLABLE", "REFRESH_REQUIRED"):
        raise ApiError("ERR_INVALID_STATE", "lot condition %s does not admit a refresh charge"
                       % lot["condition_state"])
    if int(lot["refresh_charge_count"]) >= calc.MAX_REFRESH_CYCLES:
        raise ApiError("ERR_REFRESH_CYCLES_EXHAUSTED", "refresh cycle ceiling reached")
    if lot["last_refresh_charged_at"]:
        last = parse_dt(lot["last_refresh_charged_at"])
        if DB.clock <= last + timedelta(hours=calc.REFRESH_COOLDOWN_HOURS):
            raise ApiError("ERR_REFRESH_COOLDOWN_ACTIVE", "refresh cooldown has not elapsed")

    lot["last_refresh_charged_at"] = now_ts()
    lot["refresh_charge_count"] = int(lot["refresh_charge_count"]) + 1
    lot["last_measured_open_circuit_voltage"] = voltage
    touch(lot)
    return ok(calc.serialize_lot(lot))


@bp.post("/inventory-lots/<lot_id>/scrap")
def scrap_lot(lot_id):
    authenticate(["WarehouseOperator", "ComplianceOfficer"])
    lot = must("inventory_lots", lot_id)
    body = get_body()
    manifest_id = f_str(body, "disposal_manifest_id")
    manifest = must("disposal_manifests", manifest_id)

    calc.lot_view(lot)
    if lot["condition_state"] not in ("SHELF_EXPIRED", "REFRESH_REQUIRED"):
        raise ApiError("ERR_INVALID_STATE", "lot condition %s cannot be scrapped"
                       % lot["condition_state"])
    if manifest["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "manifest is not in DRAFT")
    if int(lot["quantity_reserved"]) != 0:
        raise ApiError("ERR_LOT_RESERVED", "lot has reserved units")

    lot["scrap_manifest_id"] = manifest_id
    total = calc.manifest_totals(manifest)
    if total > calc.EPA_MANIFEST_MAX_LEAD_KG:
        lot["scrap_manifest_id"] = None
        calc.manifest_totals(manifest)
        raise ApiError("ERR_MANIFEST_LEAD_LIMIT_EXCEEDED", "manifest lead ceiling exceeded")

    touch(lot)
    touch(manifest)
    return ok(calc.serialize_lot(lot))

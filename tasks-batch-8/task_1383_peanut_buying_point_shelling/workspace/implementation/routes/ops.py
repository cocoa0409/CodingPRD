"""Dryer, DryerBooking, Warehouse, StorageReceipt (PRD 3.1, 3.6, 3.7)."""
import math
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
from authz import (ADMIN, GROWER, CLERK, authenticate, require_roles,
                   check_grower_ownership)
from db import store
from errors import err, invalid_request, invalid_state
from respond import success
from serialize import ser_dryer, ser_booking, ser_warehouse, ser_receipt
from store_ops import (get_or_404, json_body, list_response,
                       new_common_fields, req_datetime, req_enum, req_int,
                       req_pct, req_str, req_tons, touch)

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# Dryer
# ---------------------------------------------------------------------------

@bp.post("/buying-points/dryers")
def create_dryer():
    authenticate()
    data = json_body()
    bp_id = req_str(data, "buying_point_id")
    name = req_str(data, "name")
    capacity = req_int(data, "cycle_capacity_tons", minimum=1)
    hours = req_int(data, "cycle_hours", minimum=1)
    require_roles([ADMIN])
    get_or_404(store.buying_points, bp_id)
    d = new_common_fields()
    d.update({"buying_point_id": bp_id, "name": name,
              "cycle_capacity_tons": capacity, "cycle_hours": hours})
    store.dryers[d["id"]] = d
    return success(ser_dryer(d), status=201)


@bp.get("/buying-points/dryers/<d_id>")
def get_dryer(d_id):
    require_roles([ADMIN])
    d = get_or_404(store.dryers, d_id)
    return success(ser_dryer(d))


@bp.get("/buying-points/dryers")
def list_dryers():
    require_roles([ADMIN])
    items = list(store.dryers.values())
    v = request.args.get("buying_point_id")
    if v is not None:
        items = [d for d in items if d["buying_point_id"] == v]
    return list_response(items, ser_dryer)


# ---------------------------------------------------------------------------
# DryerBooking
# ---------------------------------------------------------------------------

@bp.post("/buying-points/dryer-bookings")
def create_booking():
    authenticate()
    data = json_body()
    dryer_id = req_str(data, "dryer_id")
    load_id = req_str(data, "load_id")
    tons = req_tons(data, "tons")
    starts_at = req_datetime(data, "starts_at")
    require_roles([ADMIN])
    dryer = get_or_404(store.dryers, dryer_id)
    load = get_or_404(store.loads, load_id)
    if load["drying_status"] != "REQUIRED":
        raise invalid_state("The load's drying axis must be REQUIRED to book")
    if tons != load["gross_tons"]:
        raise invalid_request("Booking tons must equal the load's gross_tons")
    cycles = math.ceil(tons / Decimal(dryer["cycle_capacity_tons"]))
    ends_at = starts_at + timedelta(hours=cycles * dryer["cycle_hours"])
    # Half-open [starts_at, ends_at) exclusivity per dryer; adjacency allowed.
    for b in store.dryer_bookings.values():
        if b["dryer_id"] != dryer_id or b["status"] != "BOOKED":
            continue
        if starts_at < b["ends_at"] and b["starts_at"] < ends_at:
            raise err("ERR_DRYER_OVERLAP", 409,
                      "The booking interval intersects another BOOKED booking")
    sheet = calc.sheet_of_record(load["id"])
    booking = new_common_fields()
    booking.update({
        "dryer_id": dryer_id,
        "load_id": load_id,
        "tons": calc.r3(tons),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "moisture_at_booking": sheet["moisture_pct"] if sheet else None,
        "actual_moisture_after": None,
        "status": "BOOKED",
    })
    store.dryer_bookings[booking["id"]] = booking
    load["drying_status"] = "BOOKED"
    touch(load)
    return success(ser_booking(booking), status=201)


@bp.get("/buying-points/dryer-bookings/<b_id>")
def get_booking(b_id):
    require_roles([ADMIN])
    b = get_or_404(store.dryer_bookings, b_id)
    return success(ser_booking(b))


@bp.get("/buying-points/dryer-bookings")
def list_bookings():
    require_roles([ADMIN])
    items = list(store.dryer_bookings.values())
    for param, field in (("dryer_id", "dryer_id"), ("load_id", "load_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b[field] == v]
    return list_response(items, ser_booking)


@bp.post("/buying-points/dryer-bookings/<b_id>/complete")
def complete_booking(b_id):
    authenticate()
    data = json_body()
    actual = req_pct(data, "actual_moisture_after")
    require_roles([ADMIN])
    b = get_or_404(store.dryer_bookings, b_id)
    if b["status"] != "BOOKED":
        raise invalid_state("Only a BOOKED booking may be completed")
    b["actual_moisture_after"] = actual
    b["status"] = "COMPLETED"
    touch(b)
    load = store.loads.get(b["load_id"])
    if load is not None:
        load["drying_status"] = ("DRIED" if actual <= calc.MOISTURE_DRYING_REQUIRED_PCT
                                 else "REQUIRED")
        touch(load)
    return success(ser_booking(b))


@bp.post("/buying-points/dryer-bookings/<b_id>/cancel")
def cancel_booking(b_id):
    require_roles([ADMIN])
    b = get_or_404(store.dryer_bookings, b_id)
    if b["status"] != "BOOKED":
        raise invalid_state("Only a BOOKED booking may be cancelled")
    b["status"] = "CANCELLED"
    touch(b)
    load = store.loads.get(b["load_id"])
    if load is not None and load["drying_status"] == "BOOKED":
        load["drying_status"] = "REQUIRED"
        touch(load)
    return success(ser_booking(b))


# ---------------------------------------------------------------------------
# Warehouse
# ---------------------------------------------------------------------------

@bp.post("/buying-points/warehouses")
def create_warehouse():
    authenticate()
    data = json_body()
    bp_id = req_str(data, "buying_point_id")
    name = req_str(data, "name")
    compartment = req_enum(data, "compartment", ("GENERAL", "SEGREGATED"))
    capacity = req_int(data, "capacity_tons", minimum=1)
    require_roles([ADMIN])
    get_or_404(store.buying_points, bp_id)
    w = new_common_fields()
    w.update({"buying_point_id": bp_id, "name": name,
              "compartment": compartment, "capacity_tons": capacity})
    store.warehouses[w["id"]] = w
    return success(ser_warehouse(w), status=201)


@bp.get("/buying-points/warehouses/<w_id>")
def get_warehouse(w_id):
    require_roles([ADMIN, CLERK])
    w = get_or_404(store.warehouses, w_id)
    return success(ser_warehouse(w))


@bp.get("/buying-points/warehouses")
def list_warehouses():
    require_roles([ADMIN, CLERK])
    items = list(store.warehouses.values())
    for param, field in (("buying_point_id", "buying_point_id"),
                         ("compartment", "compartment")):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if w[field] == v]
    return list_response(items, ser_warehouse)


# ---------------------------------------------------------------------------
# StorageReceipt — four layered gates (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.post("/buying-points/storage-receipts")
def create_receipt():
    authenticate()
    data = json_body()
    load_id = req_str(data, "load_id")
    warehouse_id = req_str(data, "warehouse_id")
    require_roles([ADMIN])
    load = get_or_404(store.loads, load_id)
    wh = get_or_404(store.warehouses, warehouse_id)
    # State (priority 6): load must be GRADED; drying gate.
    if load["status"] != "GRADED":
        raise invalid_state("Only a GRADED load may be stored")
    if load["drying_status"] not in ("NOT_REQUIRED", "DRIED"):
        raise err("ERR_DRYING_REQUIRED", 409,
                  "The load's drying axis is not satisfied for storage")
    # Compliance (priority 8): aflatoxin clearance, compartment segregation.
    if load["aflatoxin_status"] not in ("PASSED", "SEGREGATED"):
        raise err("ERR_AFLATOXIN_NOT_CLEARED", 409,
                  "The load has not cleared aflatoxin certification")
    segregated = load["aflatoxin_status"] == "SEGREGATED"
    if (segregated and wh["compartment"] != "SEGREGATED") \
            or (not segregated and wh["compartment"] != "GENERAL"):
        raise err("ERR_COMPARTMENT_SEGREGATION", 409,
                  "Warehouse compartment does not match the load's clearance")
    # Capacity (priority 9).
    if calc.wh_free_tons(wh["id"]) < load["gross_tons"]:
        raise err("ERR_WAREHOUSE_CAPACITY", 409,
                  "Warehouse free tonnage is below the load's gross tonnage")
    r = new_common_fields()
    r.update({
        "warehouse_id": wh["id"],
        "load_id": load["id"],
        "segregated": segregated,
        "tons_initial": load["gross_tons"],
        "tons_remaining": load["gross_tons"],
        "stored_at": store.clock,
        "status": "OPEN",
    })
    store.storage_receipts[r["id"]] = r
    load["status"] = "STORED"
    touch(load)
    return success(ser_receipt(r), status=201)


@bp.get("/buying-points/storage-receipts/<r_id>")
def get_receipt(r_id):
    uid, role = require_roles([ADMIN, GROWER, CLERK])
    r = get_or_404(store.storage_receipts, r_id)
    if role == GROWER:
        load = store.loads.get(r["load_id"])
        check_grower_ownership(uid, role, load["grower_id"] if load else None)
    return success(ser_receipt(r))


@bp.get("/buying-points/storage-receipts")
def list_receipts():
    uid, role = require_roles([ADMIN, GROWER, CLERK])
    items = list(store.storage_receipts.values())
    if role == GROWER:
        items = [r for r in items
                 if store.loads.get(r["load_id"]) is not None
                 and store.loads[r["load_id"]]["grower_id"] == uid]
    for param, field in (("warehouse_id", "warehouse_id"), ("load_id", "load_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    return list_response(items, ser_receipt)

"""Shipments: the buffered loadout-bay check and the tonnage handoff."""

from flask import Blueprint

import db
import response
from db import store, touch
from errors import (
    ERR_COVERED_CAPACITY_EXCEEDED,
    ERR_DEPOT_CLOSED,
    ERR_INSUFFICIENT_LOT_TONS,
    ERR_LOADOUT_BAY_CONFLICT,
    ERR_LOT_QUARANTINED,
    ERR_LOT_STATE_INVALID,
    ERR_PRODUCT_LINE_MISMATCH,
    ERR_SHIPMENT_INVALID_STATE,
    ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
    fail,
)
from middleware import auth, require_depot_ownership
from services import calc, derive, serialize
from util import D, ZERO, body, enum, filter_str, number, require, window

bp = Blueprint("shipments", __name__)

MODES = ("RAIL", "BARGE", "TRUCK")
BAY_STATUSES = ("PLANNED", "LOADED")


def _bay_peers(depot_id, exclude_id=None):
    peers = [s for s in store.shipments.values()
             if s["origin_depot_id"] == depot_id
             and s["status"] in BAY_STATUSES
             and s["id"] != exclude_id]
    peers.sort(key=lambda s: (s["load_window_start"], s["created_at"], s["_seq"]))
    return peers


def _deplete_if_drained(lot):
    if D(lot["tons_on_hand"]) == ZERO and derive.lot_reserved_tons(lot["id"]) == ZERO:
        if lot["lot_state"] == "AVAILABLE":
            lot["lot_state"] = "DEPLETED"


@bp.post("/salt/shipments")
@auth("LogisticsPlanner", "DepotManager")
def create_shipment():
    payload = body()
    require_depot_ownership(payload.get("origin_depot_id")
                           if isinstance(payload, dict) else None)
    require(payload, ["stockpile_lot_id", "origin_depot_id", "destination_depot_id",
                      "mode", "tons", "load_window_start", "load_window_end",
                      "destination_storage_kind"])
    mode = enum(payload, "mode", MODES)
    dest_kind = enum(payload, "destination_storage_kind", calc.STORAGE_KINDS)
    tons = number(payload, "tons", gt=0)
    start, end = window(payload, "load_window_start", "load_window_end")

    origin = derive.get_depot(payload["origin_depot_id"])
    destination = derive.get_depot(payload["destination_depot_id"])
    lot = derive.get_lot(payload["stockpile_lot_id"])

    if lot["lot_state"] == "QUARANTINED":
        fail(ERR_LOT_QUARANTINED, "the source lot is quarantined")
    if lot["lot_state"] != "AVAILABLE":
        fail(ERR_LOT_STATE_INVALID,
             "lot_state %s cannot be shipped" % lot["lot_state"])
    if origin["depot_state"] == "CLOSED":
        fail(ERR_DEPOT_CLOSED, "the origin depot is closed")
    if destination["depot_state"] == "CLOSED":
        fail(ERR_DEPOT_CLOSED, "the destination depot is closed")

    spec = calc.PRODUCT_SPECS[lot["product_line"]]
    if dest_kind == "OPEN_PAD" and spec["moisture_sensitive"]:
        fail(ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
             "%s may never occupy open-pad storage" % lot["product_line"])
    if dest_kind != lot["storage_kind"]:
        fail(ERR_PRODUCT_LINE_MISMATCH,
             "destination_storage_kind %s does not match the lot's storage_kind %s"
             % (dest_kind, lot["storage_kind"]))

    conflict = calc.bay_conflict(mode, start, end, _bay_peers(origin["id"]))
    if conflict is not None:
        fail(ERR_LOADOUT_BAY_CONFLICT,
             "the loadout bay is already committed by shipment %s" % conflict["id"])

    if derive.lot_available_tons(lot) < D(tons):
        fail(ERR_INSUFFICIENT_LOT_TONS,
             "the lot has %s tons available" % derive.lot_available_tons(lot))

    shipment = db.stamp()
    shipment.update({
        "stockpile_lot_id": lot["id"],
        "origin_depot_id": origin["id"],
        "destination_depot_id": destination["id"],
        "mode": mode,
        "tons": tons,
        "load_window_start": start,
        "load_window_end": end,
        "destination_storage_kind": dest_kind,
        "required_gap_minutes": calc.buffer_minutes(mode),
        "status": "PLANNED",
        "received_lot_id": None,
    })
    store.shipments[shipment["id"]] = shipment
    return response.created(serialize.shipment_json(shipment))


@bp.get("/salt/shipments/<shipment_id>")
@auth()
def read_shipment(shipment_id):
    return response.ok(serialize.shipment_json(derive.get_shipment(shipment_id)))


@bp.get("/salt/shipments")
@auth()
def list_shipments():
    rows = list(store.shipments.values())
    for name in ("stockpile_lot_id", "origin_depot_id", "destination_depot_id",
                 "status", "mode"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.shipment_json)


@bp.post("/salt/shipments/<shipment_id>/load")
@auth("DepotManager", "LogisticsPlanner")
def load_shipment(shipment_id):
    known = store.shipments.get(shipment_id)
    if known is not None:
        require_depot_ownership(known["origin_depot_id"])

    shipment = derive.get_shipment(shipment_id)
    lot = derive.get_lot(shipment["stockpile_lot_id"])
    origin = derive.get_depot(shipment["origin_depot_id"])

    if shipment["status"] != "PLANNED":
        fail(ERR_SHIPMENT_INVALID_STATE,
             "shipment status %s does not admit a load" % shipment["status"])
    if lot["lot_state"] == "QUARANTINED":
        fail(ERR_LOT_QUARANTINED, "the source lot is quarantined")
    if lot["lot_state"] != "AVAILABLE":
        fail(ERR_LOT_STATE_INVALID,
             "lot_state %s cannot be loaded" % lot["lot_state"])
    if origin["depot_state"] == "CLOSED":
        fail(ERR_DEPOT_CLOSED, "the origin depot is closed")
    if derive.lot_available_tons(lot) < D(shipment["tons"]):
        fail(ERR_INSUFFICIENT_LOT_TONS,
             "the lot has %s tons available" % derive.lot_available_tons(lot))

    shipment["status"] = "LOADED"
    lot["tons_on_hand"] = D(lot["tons_on_hand"]) - D(shipment["tons"])
    _deplete_if_drained(lot)
    touch(shipment)
    touch(lot)
    touch(origin)
    return response.ok(serialize.shipment_json(shipment))


@bp.post("/salt/shipments/<shipment_id>/receive")
@auth("DepotManager", "LogisticsPlanner")
def receive_shipment(shipment_id):
    known = store.shipments.get(shipment_id)
    if known is not None:
        require_depot_ownership(known["destination_depot_id"])

    shipment = derive.get_shipment(shipment_id)
    source_lot = derive.get_lot(shipment["stockpile_lot_id"])
    destination = derive.get_depot(shipment["destination_depot_id"])

    if shipment["status"] != "LOADED":
        fail(ERR_SHIPMENT_INVALID_STATE,
             "shipment status %s does not admit a receipt" % shipment["status"])
    if destination["depot_state"] == "CLOSED":
        fail(ERR_DEPOT_CLOSED, "the destination depot is closed")

    kind = shipment["destination_storage_kind"]
    spec = calc.PRODUCT_SPECS[source_lot["product_line"]]
    if kind != "COVERED" and spec["moisture_sensitive"]:
        fail(ERR_UNCOVERED_STORAGE_NOT_ALLOWED,
             "%s may never occupy open-pad storage" % source_lot["product_line"])

    if kind == "COVERED":
        stored = derive.depot_covered_stored(destination["id"])
        capacity = D(destination["covered_capacity_tons"])
    else:
        stored = derive.depot_open_pad_stored(destination["id"])
        capacity = D(destination["open_pad_capacity_tons"])
    if capacity - stored < D(shipment["tons"]):
        fail(ERR_COVERED_CAPACITY_EXCEEDED,
             "the destination has %s tons of free %s space"
             % (capacity - stored, kind))

    lot = db.stamp()
    lot.update({
        "depot_id": destination["id"],
        "treatment_batch_id": source_lot["treatment_batch_id"],
        "product_line": source_lot["product_line"],
        "purity_pct_nacl": source_lot["purity_pct_nacl"],
        "storage_kind": kind,
        "tons_on_hand": D(shipment["tons"]),
        "lot_state": "AVAILABLE",
        "quarantine_reason": None,
    })
    store.lots[lot["id"]] = lot

    shipment["status"] = "RECEIVED"
    shipment["received_lot_id"] = lot["id"]
    derive.maybe_auto_surge(destination)
    touch(shipment)
    touch(destination)
    return response.ok(serialize.shipment_json(shipment))


@bp.post("/salt/shipments/<shipment_id>/cancel")
@auth("LogisticsPlanner", "DepotManager")
def cancel_shipment(shipment_id):
    shipment = derive.get_shipment(shipment_id)
    if shipment["status"] not in BAY_STATUSES:
        fail(ERR_SHIPMENT_INVALID_STATE,
             "shipment status %s does not admit a cancellation" % shipment["status"])

    was_loaded = shipment["status"] == "LOADED"
    shipment["status"] = "CANCELLED"
    touch(shipment)
    if was_loaded:
        lot = derive.get_lot(shipment["stockpile_lot_id"])
        origin = derive.get_depot(shipment["origin_depot_id"])
        lot["tons_on_hand"] = D(lot["tons_on_hand"]) + D(shipment["tons"])
        if lot["lot_state"] == "DEPLETED":
            lot["lot_state"] = "AVAILABLE"
        touch(lot)
        touch(origin)
    return response.ok(serialize.shipment_json(shipment))

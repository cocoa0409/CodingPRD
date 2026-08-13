"""Supply contract + rail shipment endpoints."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import (
    err_not_found,
    err_referenced_not_found,
    err_invalid_request,
    err_invalid_state,
    err_window_invalid,
    err_shipment_window_violation,
    err_contract_not_active,
    err_volume_invalid,
)

bp = Blueprint("supply", __name__)

RW_ROLES = ["SupplyAdmin"]
READ_SC_ROLES = ["SupplyAdmin", "SupplyPlanner"]
READ_RS_ROLES = ["SupplyAdmin", "SupplyPlanner", "Dispatcher"]

RAIL_TRANSITIONS = {
    ("TENDERED", "IN_TRANSIT"),
    ("IN_TRANSIT", "ARRIVED"),
    ("ARRIVED", "UNLOADED"),
    ("TENDERED", "CANCELLED"),
    ("IN_TRANSIT", "CANCELLED"),
}
RAIL_STATES = {"TENDERED", "IN_TRANSIT", "ARRIVED", "UNLOADED", "CANCELLED"}


@bp.route("/supply-contracts", methods=["POST"])
def create_supply_contract():
    caller = mw.authenticate()
    mw.authorize(caller, RW_ROLES)
    body = mw.get_json_body(required=True)
    terminal_id = mw.req_string(body, "terminal_id")
    supplier_name = mw.req_string(body, "supplier_name")
    contracted_volume_gal = mw.req_int(body, "contracted_volume_gal")
    receipt_window_start = mw.req_date(body, "receipt_window_start")
    receipt_window_end = mw.req_date(body, "receipt_window_end")

    # body FKs (priority 5)
    if terminal_id not in db.terminals:
        raise err_referenced_not_found("terminal_id does not resolve")
    # business (priority 10): window coherence first (inverted-window contract is
    # the ERR_WINDOW_INVALID fixture of §3.2), then positivity
    if receipt_window_end < receipt_window_start:
        raise err_window_invalid("receipt_window_end < receipt_window_start")
    if contracted_volume_gal <= 0:
        raise err_volume_invalid("contracted_volume_gal must be > 0")

    now = svc.stamp_now()
    c = {
        "id": db.new_id(),
        "terminal_id": terminal_id,
        "supplier_name": supplier_name,
        "contracted_volume_gal": contracted_volume_gal,
        "delivered_volume_gal": 0,
        "receipt_window_start": receipt_window_start,
        "receipt_window_end": receipt_window_end,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.supply_contracts[c["id"]] = c
    return resp.created(ser.serialize_supply_contract(c))


@bp.route("/supply-contracts/<cid>", methods=["GET"])
def get_supply_contract(cid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_SC_ROLES)
    c = db.supply_contracts.get(cid)
    if c is None:
        raise err_not_found()
    return resp.ok(ser.serialize_supply_contract(c))


@bp.route("/supply-contracts", methods=["GET"])
def list_supply_contracts():
    caller = mw.authenticate()
    mw.authorize(caller, READ_SC_ROLES)
    limit, offset = mw.pagination_params()
    terminal_id = mw.opt_query_string("terminal_id")
    status = mw.opt_query_enum(
        "status", {"DRAFT", "ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED"}
    )
    items = list(db.supply_contracts.values())
    if terminal_id is not None:
        items = [c for c in items if c["terminal_id"] == terminal_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_supply_contract(c) for c in page], limit, offset, total)


@bp.route("/supply-contracts/<cid>/activate", methods=["POST"])
def activate_supply_contract(cid):
    caller = mw.authenticate()
    mw.authorize(caller, RW_ROLES)
    c = db.supply_contracts.get(cid)
    if c is None:
        raise err_not_found()
    if c["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT supply contract can be activated")
    if c["receipt_window_end"] < c["receipt_window_start"]:
        raise err_window_invalid("receipt_window_end < receipt_window_start")
    c["status"] = "ACTIVE"
    svc.touch(c)
    return resp.ok(ser.serialize_supply_contract(c))


@bp.route("/supply-contracts/<cid>/cancel", methods=["POST"])
def cancel_supply_contract(cid):
    caller = mw.authenticate()
    mw.authorize(caller, RW_ROLES)
    c = db.supply_contracts.get(cid)
    if c is None:
        raise err_not_found()
    if c["status"] not in ("DRAFT", "ACTIVE"):
        raise err_invalid_state("Supply contract cannot be cancelled from its current state")
    c["status"] = "CANCELLED"
    svc.touch(c)
    for s in db.rail_shipments.values():
        if s["supply_contract_id"] == c["id"] and s["status"] in ("TENDERED", "IN_TRANSIT"):
            s["status"] = "CANCELLED"
            svc.touch(s)
    return resp.ok(ser.serialize_supply_contract(c))


# ---------------------------------------------------------------------------
# Rail shipments
# ---------------------------------------------------------------------------

@bp.route("/rail-shipments", methods=["POST"])
def create_rail_shipment():
    caller = mw.authenticate()
    mw.authorize(caller, RW_ROLES)
    body = mw.get_json_body(required=True)
    supply_contract_id = mw.req_string(body, "supply_contract_id")
    volume_gal = mw.req_int(body, "volume_gal")
    railcar_count = mw.req_int(body, "railcar_count")
    scheduled_arrival_date = mw.req_date(body, "scheduled_arrival_date")

    c = db.supply_contracts.get(supply_contract_id)
    if c is None:
        raise err_referenced_not_found("supply_contract_id does not resolve")

    if c["status"] in ("COMPLETED", "DEFAULTED", "CANCELLED"):
        raise err_contract_not_active("No shipments may be created under a terminal-state contract")

    if volume_gal <= 0 or railcar_count <= 0:
        raise err_volume_invalid("volume_gal and railcar_count must be > 0")
    if not (c["receipt_window_start"] <= scheduled_arrival_date <= c["receipt_window_end"]):
        raise err_shipment_window_violation()

    now = svc.stamp_now()
    s = {
        "id": db.new_id(),
        "supply_contract_id": supply_contract_id,
        "terminal_id": c["terminal_id"],
        "volume_gal": volume_gal,
        "railcar_count": railcar_count,
        "scheduled_arrival_date": scheduled_arrival_date,
        "unloaded_at": None,
        "status": "TENDERED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.rail_shipments[s["id"]] = s
    return resp.created(ser.serialize_rail_shipment(s))


@bp.route("/rail-shipments/<sid>", methods=["GET"])
def get_rail_shipment(sid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_RS_ROLES)
    s = db.rail_shipments.get(sid)
    if s is None:
        raise err_not_found()
    return resp.ok(ser.serialize_rail_shipment(s))


@bp.route("/rail-shipments", methods=["GET"])
def list_rail_shipments():
    caller = mw.authenticate()
    mw.authorize(caller, READ_RS_ROLES)
    limit, offset = mw.pagination_params()
    supply_contract_id = mw.opt_query_string("supply_contract_id")
    terminal_id = mw.opt_query_string("terminal_id")
    status = mw.opt_query_enum("status", RAIL_STATES)
    items = list(db.rail_shipments.values())
    if supply_contract_id is not None:
        items = [s for s in items if s["supply_contract_id"] == supply_contract_id]
    if terminal_id is not None:
        items = [s for s in items if s["terminal_id"] == terminal_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_rail_shipment(s) for s in page], limit, offset, total)


@bp.route("/rail-shipments/<sid>/transition", methods=["POST"])
def transition_rail_shipment(sid):
    caller = mw.authenticate()
    mw.authorize(caller, RW_ROLES)
    s = db.rail_shipments.get(sid)
    if s is None:
        raise err_not_found()
    body = mw.get_json_body(required=True)
    to_state = mw.req_enum(body, "to_state", RAIL_STATES)

    if (s["status"], to_state) not in RAIL_TRANSITIONS:
        raise err_invalid_state(f"Cannot transition rail shipment {s['status']} -> {to_state}")

    c = db.supply_contracts[s["supply_contract_id"]]
    if to_state == "UNLOADED":
        # cross-entity state gate: contract must be ACTIVE
        if c["status"] != "ACTIVE":
            raise err_contract_not_active("Supply contract must be ACTIVE to unload")

    s["status"] = to_state
    if to_state == "UNLOADED":
        s["unloaded_at"] = svc.stamp_now()
        terminal = db.terminals[s["terminal_id"]]
        terminal["on_hand_gal"] += s["volume_gal"]
        svc.touch(terminal)
        c["delivered_volume_gal"] += s["volume_gal"]
        if c["delivered_volume_gal"] >= c["contracted_volume_gal"]:
            c["status"] = "COMPLETED"
        svc.touch(c)
    svc.touch(s)
    return resp.ok(ser.serialize_rail_shipment(s))

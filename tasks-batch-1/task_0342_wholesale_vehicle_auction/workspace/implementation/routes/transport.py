"""GatePass, Carrier, TransportOrder endpoints (PRD §3.11)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, require_role
from response import success_object, success_list
from services.common import (
    base_record, touch, get_body, require_str, require_int, optional_int,
    public, list_collection,
)
from services import lookup

bp = Blueprint("transport", __name__)


# ===== GatePass =============================================================
@bp.route("/auction/gate-passes", methods=["GET"])
def list_gate_passes():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    filters = {
        "settlement_id": request.args.get("settlement_id"),
        "buyer_id": request.args.get("buyer_id"),
        "status": request.args.get("status"),
    }
    items, limit, offset, total = list_collection(db.gate_passes, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/gate-passes/<gate_pass_id>", methods=["GET"])
def get_gate_pass(gate_pass_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    with db.lock:
        gp = lookup.get_gate_pass(gate_pass_id)
        return success_object(public(gp))


@bp.route("/auction/gate-passes/<gate_pass_id>/redeem", methods=["POST"])
def redeem_gate_pass(gate_pass_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        gp = lookup.get_gate_pass(gate_pass_id)
        if gp["status"] != "ISSUED":
            raise ApiError("ERR_GATE_PASS_NOT_ISSUED", "Gate pass not ISSUED.")
        # require a DISPATCHED transport order for the same settlement
        has_dispatched = any(
            t["settlement_id"] == gp["settlement_id"] and t["status"] == "DISPATCHED"
            for t in db.transport_orders.values()
        )
        if not has_dispatched:
            raise ApiError("ERR_NO_DISPATCHED_TRANSPORT", "No dispatched transport.")
        gp["status"] = "REDEEMED"
        touch(gp)
        return success_object(public(gp))


# ===== Carrier ==============================================================
@bp.route("/auction/carriers", methods=["POST"])
def create_carrier():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    carrier_name = require_str(body, "carrier_name")
    buffer = optional_int(body, "turnaround_buffer_minutes", default=30, minimum=0)
    with db.lock:
        rec = base_record()
        rec.update({
            "carrier_name": carrier_name,
            "turnaround_buffer_minutes": buffer,
            "status": "ACTIVE",
        })
        db.carriers[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/carriers", methods=["GET"])
def list_carriers():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    filters = {"status": request.args.get("status")}
    items, limit, offset, total = list_collection(db.carriers, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/carriers/<carrier_id>", methods=["GET"])
def get_carrier(carrier_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    with db.lock:
        c = lookup.get_carrier(carrier_id)
        return success_object(public(c))


@bp.route("/auction/carriers/<carrier_id>/suspend", methods=["POST"])
def suspend_carrier(carrier_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        c = lookup.get_carrier(carrier_id)
        c["status"] = "SUSPENDED"
        touch(c)
        return success_object(public(c))


# ===== TransportOrder =======================================================
@bp.route("/auction/transport-orders", methods=["POST"])
def create_transport_order():
    user_id, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    body = get_body()
    settlement_id = require_str(body, "settlement_id")
    carrier_id = require_str(body, "carrier_id")
    pickup_start = require_int(body, "pickup_start_minute", minimum=0)
    pickup_end = require_int(body, "pickup_end_minute")
    if not (pickup_start < pickup_end):
        raise ApiError("ERR_VALIDATION", "Invalid pickup window.")

    with db.lock:
        # existence (priority 4): body FKs
        settlement = lookup.get_settlement(settlement_id)
        carrier = lookup.get_carrier(carrier_id)
        # ownership (priority 3): Buyer may only book under own buyer ownership.
        # The transport order's buyer is the settlement's buyer.
        if role == "Buyer" and settlement["buyer_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning buyer.")

        # temporal window (priority 8): buffered closed-interval separation
        buffer = carrier["turnaround_buffer_minutes"]
        for other in db.transport_orders.values():
            if other["carrier_id"] != carrier_id:
                continue
            if other["status"] == "CANCELLED":
                continue
            o_start = other["pickup_start_minute"]
            o_end = other["pickup_end_minute"]
            # closed intervals; require gap >= buffer between them.
            # gap = distance between intervals (0 if they overlap/touch).
            if pickup_start > o_end:
                gap = pickup_start - o_end
            elif o_start > pickup_end:
                gap = o_start - pickup_end
            else:
                gap = 0
            if gap < buffer:
                raise ApiError("ERR_CARRIER_WINDOW_CONFLICT", "Carrier window conflict.")

        rec = base_record()
        rec.update({
            "settlement_id": settlement_id,
            "carrier_id": carrier_id,
            "buyer_id": settlement["buyer_id"],
            "pickup_start_minute": pickup_start,
            "pickup_end_minute": pickup_end,
            "status": "REQUESTED",
        })
        db.transport_orders[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/transport-orders", methods=["GET"])
def list_transport_orders():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    filters = {
        "settlement_id": request.args.get("settlement_id"),
        "carrier_id": request.args.get("carrier_id"),
        "status": request.args.get("status"),
    }
    items, limit, offset, total = list_collection(db.transport_orders, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/transport-orders/<transport_id>", methods=["GET"])
def get_transport_order(transport_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    with db.lock:
        t = lookup.get_transport_order(transport_id)
        return success_object(public(t))


@bp.route("/auction/transport-orders/<transport_id>/dispatch", methods=["POST"])
def dispatch_transport(transport_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        t = lookup.get_transport_order(transport_id)
        if t["status"] != "REQUESTED":
            raise ApiError("ERR_TRANSPORT_NOT_REQUESTED", "Transport not REQUESTED.")
        settlement = db.settlements.get(t["settlement_id"])
        if settlement is None or settlement["status"] != "CLEARED":
            raise ApiError("ERR_SETTLEMENT_NOT_CLEARED", "Settlement not CLEARED.")
        carrier = db.carriers.get(t["carrier_id"])
        if carrier is None or carrier["status"] != "ACTIVE":
            raise ApiError("ERR_CARRIER_SUSPENDED", "Carrier suspended.")
        t["status"] = "DISPATCHED"
        touch(t)
        return success_object(public(t))


@bp.route("/auction/transport-orders/<transport_id>/deliver", methods=["POST"])
def deliver_transport(transport_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        t = lookup.get_transport_order(transport_id)
        if t["status"] != "DISPATCHED":
            raise ApiError("ERR_TRANSPORT_NOT_DISPATCHED", "Transport not DISPATCHED.")
        t["status"] = "DELIVERED"
        touch(t)
        return success_object(public(t))


@bp.route("/auction/transport-orders/<transport_id>/cancel", methods=["POST"])
def cancel_transport(transport_id):
    user_id, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    with db.lock:
        t = lookup.get_transport_order(transport_id)
        if role == "Buyer" and t["buyer_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning buyer.")
        if t["status"] != "REQUESTED":
            raise ApiError("ERR_TRANSPORT_NOT_REQUESTED", "Transport not REQUESTED.")
        t["status"] = "CANCELLED"
        touch(t)
        return success_object(public(t))

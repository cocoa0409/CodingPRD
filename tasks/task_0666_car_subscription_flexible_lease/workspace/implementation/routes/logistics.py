"""Courier & delivery slot routes (PRD §3.10)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from clock import parse_iso
from db import db, stamp_create
from middleware import get_identity, require_roles, parse_pagination
from response import object_response, array_response
from services import serialize, common

bp = Blueprint("logistics", __name__)

SLOT_KINDS = {"DELIVERY", "RETURN"}


# --------------------------- Courier ---------------------------
@bp.route("/couriers", methods=["POST"])
def create_courier():
    _, role = get_identity()
    require_roles(role, {"FleetOperator", "PlatformAdmin"})  # shared (PRD §3.10)
    body = common.get_body()
    name = common.require_str(body, "name")
    fleet_id = common.require_str(body, "fleet_id")
    buffer_minutes = common.optional_int(body, "buffer_minutes", default=30, min_value=0)
    common.resolve(db.fleets, fleet_id)
    rec = {
        "name": name,
        "fleet_id": fleet_id,
        "buffer_minutes": buffer_minutes,
    }
    stamp_create(rec)
    db.couriers[rec["id"]] = rec
    return object_response(serialize.serialize_courier(rec), 201)


@bp.route("/couriers/<cid>", methods=["GET"])
def get_courier(cid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin"})
    rec = common.resolve(db.couriers, cid)
    return object_response(serialize.serialize_courier(rec))


@bp.route("/couriers", methods=["GET"])
def list_couriers():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin"})
    limit, offset = parse_pagination()
    records = list(db.couriers.values())
    records = common.filter_equals(records, "fleet_id", request.args.get("fleet_id"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_courier(r) for r in page], limit, offset, total)


# --------------------------- DeliverySlot ---------------------------
@bp.route("/delivery-slots", methods=["POST"])
def create_slot():
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.10)
    body = common.get_body()
    courier_id = common.require_str(body, "courier_id")
    subscription_id = common.require_str(body, "subscription_id")
    kind = common.require_enum(body, "kind", SLOT_KINDS)
    start_iso = common.require_str(body, "window_start_iso")
    end_iso = common.require_str(body, "window_end_iso")

    courier = common.resolve(db.couriers, courier_id)
    sub = common.resolve(db.subscriptions, subscription_id)

    try:
        start = parse_iso(start_iso)
        end = parse_iso(end_iso)
    except (ValueError, TypeError):
        raise errors.invalid_request("window_start_iso/window_end_iso must be ISO 8601.")
    # end strictly after start (PRD §3.10).
    if not (end > start):
        raise errors.invalid_request("window_end_iso must be strictly after window_start_iso.")

    # priority 11: vehicle half-open overlap (ERR_VEHICLE_SLOT_OVERLAP).
    _check_vehicle_overlap(sub, start, end)
    # priority 12: courier closed-interval + buffer (ERR_COURIER_BUFFER_CONFLICT).
    _check_courier_buffer(courier, start, end)

    rec = {
        "courier_id": courier_id,
        "subscription_id": subscription_id,
        "kind": kind,
        "window_start_iso": start_iso,
        "window_end_iso": end_iso,
        "status": "SCHEDULED",
    }
    stamp_create(rec)
    db.delivery_slots[rec["id"]] = rec
    return object_response(serialize.serialize_delivery_slot(rec), 201)


@bp.route("/delivery-slots/<sid>", methods=["GET"])
def get_slot(sid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    rec = common.resolve(db.delivery_slots, sid)
    return object_response(serialize.serialize_delivery_slot(rec))


@bp.route("/delivery-slots", methods=["GET"])
def list_slots():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    records = list(db.delivery_slots.values())
    records = common.filter_equals(records, "courier_id", request.args.get("courier_id"))
    records = common.filter_equals(records, "subscription_id", request.args.get("subscription_id"))
    records = common.filter_equals(records, "kind", request.args.get("kind"))
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_delivery_slot(r) for r in page], limit, offset, total)


def _check_vehicle_overlap(sub, start, end):
    """PRD §3.10: a new slot must not overlap a non-cancelled slot bound to the same
    vehicle's active reservation window, half-open [start, end). Adjacency (end==start)
    is allowed. The vehicle is the subscription's active_vehicle_id."""
    for other in db.delivery_slots.values():
        if other["status"] == "CANCELLED":
            continue
        if other["subscription_id"] != sub["id"]:
            continue
        o_start = parse_iso(other["window_start_iso"])
        o_end = parse_iso(other["window_end_iso"])
        # half-open overlap: start < o_end and o_start < end.
        if start < o_end and o_start < end:
            raise errors.vehicle_slot_overlap()


def _check_courier_buffer(courier, start, end):
    """PRD §3.10: a new slot must keep at least courier.buffer_minutes clear gap from
    every other non-cancelled slot of the same courier; each slot is a closed interval
    padded by the buffer on both sides, and padded closed intervals may not touch."""
    buffer = timedelta(minutes=courier["buffer_minutes"])
    new_lo = start - buffer
    new_hi = end + buffer
    for other in db.delivery_slots.values():
        if other["status"] == "CANCELLED":
            continue
        if other["courier_id"] != courier["id"]:
            continue
        o_start = parse_iso(other["window_start_iso"])
        o_end = parse_iso(other["window_end_iso"])
        o_lo = o_start - buffer
        o_hi = o_end + buffer
        # padded closed intervals touch/overlap when new_lo <= o_hi and o_lo <= new_hi.
        if new_lo <= o_hi and o_lo <= new_hi:
            raise errors.courier_buffer_conflict()

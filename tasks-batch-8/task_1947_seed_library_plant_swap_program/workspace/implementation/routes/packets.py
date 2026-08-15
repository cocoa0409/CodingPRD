"""SeedPacket endpoints: list/get/void/dispose."""

from flask import Blueprint, request
from db import db
from middleware import require_roles
from validate import get_body, opt_enum, parse_pagination
from response import success_object, success_list
from errors import (not_found, invalid_state, already_terminal, invalid_enum,
                    invalid_request, ApiError)
from services.core import check_lot_depleted

bp = Blueprint("packets", __name__)

PACKET_STATUSES = {"AVAILABLE", "CHECKED_OUT", "RETURNED", "RECALLED", "VOIDED", "DISCARDED"}
PACKET_TERMINAL = {"VOIDED", "DISCARDED"}


def packet_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def get_packet_or_404(packet_id):
    p = db.packets.get(packet_id)
    if p is None:
        raise not_found("Seed packet not found.")
    return p


@bp.get("/api/seed-packets")
def list_packets():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    lot_id = request.args.get("lot_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in PACKET_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.packets.values(), key=lambda p: p["_seq"])
    if lot_id:
        items = [p for p in items if p["lot_id"] == lot_id]
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([packet_view(p) for p in page], limit, offset, total)


@bp.get("/api/seed-packets/<packet_id>")
def get_packet(packet_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    p = get_packet_or_404(packet_id)
    return success_object(packet_view(p))


@bp.post("/api/seed-packets/<packet_id>/void")
def void_packet(packet_id):
    require_roles("ProgramAdmin")
    p = get_packet_or_404(packet_id)
    body = get_body()
    mode = opt_enum(body, "mode", {"REINTEGRATE", "DISCARD"})
    if mode is None:
        raise invalid_request("Missing required field: mode")
    if p["status"] in PACKET_TERMINAL:
        raise already_terminal("Packet is in a terminal state.")
    if p["status"] != "AVAILABLE":
        raise invalid_state("Only an AVAILABLE packet can be voided.")
    lot = db.lots.get(p["lot_id"])
    p["status"] = "VOIDED"
    db.touch(p)
    if lot is not None:
        lot["seeds_in_packets"] -= p["seeds_count"]
        if mode == "REINTEGRATE":
            lot["seeds_remaining"] += p["seeds_count"]
        else:
            lot["seeds_discarded"] += p["seeds_count"]
        db.touch(lot)
        check_lot_depleted(lot)
    return success_object(packet_view(p))


@bp.post("/api/seed-packets/<packet_id>/dispose")
def dispose_packet(packet_id):
    require_roles("ProgramAdmin")
    p = get_packet_or_404(packet_id)
    if p["status"] in PACKET_TERMINAL:
        raise already_terminal("Packet is in a terminal state.")
    if p["status"] != "RECALLED":
        raise invalid_state("Only a RECALLED packet can be disposed.")
    for c in db.checkouts.values():
        if c["packet_id"] == p["id"] and c["status"] in (
                "ACTIVE", "OVERDUE", "RETURNED", "DISPUTED"):
            raise invalid_state(
                "A live checkout still references this packet.")
    lot = db.lots.get(p["lot_id"])
    p["status"] = "DISCARDED"
    db.touch(p)
    if lot is not None:
        lot["seeds_in_packets"] -= p["seeds_count"]
        lot["seeds_discarded"] += p["seeds_count"]
        db.touch(lot)
    return success_object(packet_view(p))

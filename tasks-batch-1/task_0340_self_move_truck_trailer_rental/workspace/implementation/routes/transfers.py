"""DropOffTransfer endpoints: create, fetch, list, approve, reject, complete."""
from flask import Blueprint, request

import db
import lookup
import validate as V
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public, public_list
from services import domain

bp = Blueprint("transfers", __name__)

FM_LA = {"FleetManager", "LocationAgent"}


@bp.route("/rental/transfers", methods=["POST"])
def create_transfer():
    _, role = authenticate()
    require_role(role, FM_LA)
    body = V.get_json()
    V.require_fields(body, ["equipment_id", "to_location_id", "reason"])
    eq = lookup.require_equipment(body["equipment_id"])
    to_loc = lookup.require_location(body["to_location_id"])
    reason = V.require_enum(body, "reason", {"ONE_WAY_REBALANCE", "FLEET_REBALANCE"})

    from_location_id = eq["current_location_id"]

    # Transfer validity (priority 17).
    if (from_location_id is None
            or body["to_location_id"] == from_location_id
            or to_loc["status"] != "OPEN"):
        raise err("ERR_INVALID_TRANSFER", "Invalid transfer parameters.")

    # Lifecycle occupancy (priority 19).
    if domain.open_transfer_for_equipment(eq["id"]) is not None:
        raise err("ERR_TRANSFER_IN_PROGRESS", "Equipment already has an open transfer.")

    row = db.make_common(db.transfers)
    row.update({
        "equipment_id": eq["id"],
        "from_location_id": from_location_id,
        "to_location_id": body["to_location_id"],
        "reason": reason,
        "status": "REQUESTED",
    })
    db.transfers.put(row)
    return success(public(row), status=201)


@bp.route("/rental/transfers/<rid>", methods=["GET"])
def get_transfer(rid):
    _, role = authenticate()
    require_role(role, FM_LA)
    return success(public(lookup.require_transfer(rid)))


@bp.route("/rental/transfers", methods=["GET"])
def list_transfers():
    _, role = authenticate()
    require_role(role, FM_LA)
    limit, offset = V.parse_pagination()
    rows = db.transfers.all()
    for field in ("equipment_id", "from_location_id", "to_location_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [r for r in rows if r.get(field) == val]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


@bp.route("/rental/transfers/<rid>/approve", methods=["POST"])
def approve_transfer(rid):
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    t = lookup.require_transfer(rid)
    if t["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a REQUESTED transfer may be approved.")

    to_loc = db.locations.get(t["to_location_id"])
    if to_loc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Destination location is not OPEN.")
    if to_loc["on_lot_count"] >= to_loc["lot_capacity"]:
        raise err("ERR_RETURN_LOT_FULL", "Destination lot is full.")

    eq = db.equipment.get(t["equipment_id"])
    if eq is not None and eq["status"] == "AVAILABLE":
        eq["status"] = "IN_TRANSIT"
        db.touch(eq)
        domain.recompute_on_lot_count(t["from_location_id"])

    t["status"] = "APPROVED"
    db.touch(t)
    return success(public(t))


@bp.route("/rental/transfers/<rid>/reject", methods=["POST"])
def reject_transfer(rid):
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    t = lookup.require_transfer(rid)
    if t["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a REQUESTED transfer may be rejected.")
    t["status"] = "REJECTED"
    db.touch(t)
    return success(public(t))


@bp.route("/rental/transfers/<rid>/complete", methods=["POST"])
def complete_transfer(rid):
    _, role = authenticate()
    require_role(role, {"LocationAgent"})
    t = lookup.require_transfer(rid)
    if t["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED transfer may be completed.")

    to_loc = db.locations.get(t["to_location_id"])
    if to_loc["on_lot_count"] >= to_loc["lot_capacity"]:
        raise err("ERR_RETURN_LOT_FULL", "Destination lot is full.")

    eq = db.equipment.get(t["equipment_id"])
    if eq is not None:
        eq["status"] = "AVAILABLE"
        eq["current_location_id"] = t["to_location_id"]
        db.touch(eq)
        domain.recompute_on_lot_count(t["to_location_id"])
        domain.recompute_on_lot_count(t["from_location_id"])

    t["status"] = "COMPLETED"
    db.touch(t)
    return success(public(t))

"""Flat allocation endpoints: reads, manual release (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ALLOCATION_INVALID_STATE,
    ERR_ROOM_INVALID_STATE,
)
from middleware import authorized, check_grower_scope, ALL_ROLES
from response import success_object
from routes.helpers import list_response, public, sorted_items
from services.domain import release_allocation
from validate import get_body, require_path_resource

bp = Blueprint("allocations", __name__)


def _allocation_grower_id(alloc):
    lot = db["lots"].get(alloc["lot_id"])
    return lot["grower_id"] if lot is not None else None


@bp.get("/allocations/<allocationId>")
def get_allocation(allocationId):
    caller = authorized(list(ALL_ROLES))
    alloc = require_path_resource("allocations", allocationId)
    check_grower_scope(caller, _allocation_grower_id(alloc))
    return success_object(public(alloc))


@bp.get("/allocations")
def list_allocations():
    caller = authorized(list(ALL_ROLES))
    items = sorted_items("allocations")
    if caller.role == "Grower":
        # Force-filtered to allocations of the caller's own lots (PRD 2.1).
        items = [a for a in items if _allocation_grower_id(a) == caller.user_id]
    f_room = request.args.get("room_id")
    f_lot = request.args.get("lot_id")
    f_status = request.args.get("status")
    if f_room is not None:
        items = [a for a in items if a["room_id"] == f_room]
    if f_lot is not None:
        items = [a for a in items if a["lot_id"] == f_lot]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return list_response(items)


@bp.post("/allocations/<allocationId>/release")
def release_allocation_manual(allocationId):
    authorized(["Admin", "StorageOperator"])
    alloc = require_path_resource("allocations", allocationId)
    get_body()
    room = db["ca_rooms"][alloc["room_id"]]
    # Tier 8 fixed order: room before allocation.
    if room["status"] != "OPENED":
        raise_error(ERR_ROOM_INVALID_STATE,
                    f"release requires an OPENED room, found {room['status']}")
    if alloc["status"] != "ACTIVE":
        raise_error(ERR_ALLOCATION_INVALID_STATE,
                    f"allocation is not ACTIVE (found {alloc['status']})")
    release_allocation(alloc, room, "MANUAL")
    return success_object(public(alloc))

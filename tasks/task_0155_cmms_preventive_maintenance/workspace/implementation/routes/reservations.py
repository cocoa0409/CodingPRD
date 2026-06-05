"""PartReservation routes (PRD §3.7, §4) — reserve, list, fetch, release.

Reserve is OCC-guarded on the parent SparePart (PRD §2.6).
"""
from flask import Blueprint, request

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import require_str, require_int, parse_pagination, paginate
from response import object_response, array_response
from services import calc

bp = Blueprint("reservations", __name__)

RESERVABLE_STATES = {"UNASSIGNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD"}


@bp.post("/work-orders/<wid>/reservations")
def create_reservation(wid):
    _, role = authenticate()
    authorize(role, ["InventoryClerk"])
    body = get_json_body()
    with db.LOCK:
        wo = db.work_orders.get(wid)
        if wo is None:
            raise errors.not_found()
        spare_part_id = require_str(body, "spare_part_id")
        qty = require_int(body, "qty", minimum=1)
        if "expected_spare_part_version" not in body or body["expected_spare_part_version"] is None:
            raise errors.invalid_request("Missing required field: expected_spare_part_version.")
        expected = body["expected_spare_part_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("expected_spare_part_version must be an integer.")

        # FK existence (priority 4).
        part = db.spare_parts.get(spare_part_id)
        if part is None:
            raise errors.reference_not_found("spare_part_id does not reference an existing spare part.")

        # State (priority 6): WO must admit reservations (not DRAFT, not terminal).
        if wo["execution_status"] not in RESERVABLE_STATES:
            raise errors.invalid_state("Work order is not in a state that admits reservations.")

        # OCC (priority 7) on the SparePart.
        if expected != part["version"]:
            raise errors.stale_version("expected_spare_part_version does not match the part's current version.")

        # Stock availability (priority 13).
        available = part["on_hand_qty"] - part["reserved_qty"]
        if available < qty:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_STOCK,
                                  "Insufficient available stock for the requested quantity.", 422)

        rec = db.new_record()
        rec.update({
            "work_order_id": wid,
            "spare_part_id": spare_part_id,
            "qty": qty,
            "status": "RESERVED",
            "committed_cost_cents": 0,
        })
        db.part_reservations[rec["id"]] = rec
        # recompute reserved_qty (bumps the part version, PRD §3.7).
        calc.recompute_reserved_qty(part)
        # WO parts_status -> RESERVED (NONE on first, stays RESERVED after).
        if wo["parts_status"] == "NONE":
            wo["parts_status"] = "RESERVED"
            db.touch(wo)
        return object_response(serialize.part_reservation(rec), 201)


@bp.get("/work-orders/<wid>/reservations")
def list_wo_reservations(wid):
    _, role = authenticate()
    authorize(role, ["InventoryClerk", "Planner", "MaintenanceManager", "Technician"])
    limit, offset = parse_pagination()
    with db.LOCK:
        if wid not in db.work_orders:
            raise errors.not_found()
        items = sorted(
            (r for r in db.part_reservations.values() if r["work_order_id"] == wid),
            key=lambda r: r["_seq"])
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.part_reservation(r) for r in page],
                              limit, offset, total)


@bp.get("/reservations/<rid>")
def get_reservation(rid):
    _, role = authenticate()
    authorize(role, ["InventoryClerk", "Planner", "MaintenanceManager"])
    with db.LOCK:
        rec = db.part_reservations.get(rid)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.part_reservation(rec), 200)


@bp.get("/reservations")
def list_reservations():
    _, role = authenticate()
    authorize(role, ["InventoryClerk", "Planner", "MaintenanceManager"])
    limit, offset = parse_pagination()
    spare_part_id = request.args.get("spare_part_id")
    with db.LOCK:
        items = sorted(db.part_reservations.values(), key=lambda r: r["_seq"])
        if spare_part_id is not None:
            items = [r for r in items if r["spare_part_id"] == spare_part_id]
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.part_reservation(r) for r in page],
                              limit, offset, total)


@bp.post("/reservations/<rid>/release")
def release_reservation(rid):
    _, role = authenticate()
    authorize(role, ["InventoryClerk"])
    with db.LOCK:
        rec = db.part_reservations.get(rid)
        if rec is None:
            raise errors.not_found()
        # State (priority 6): reservation must be RESERVED and parent WO not CLOSED.
        if rec["status"] != "RESERVED":
            raise errors.invalid_state("Reservation is not RESERVED.")
        wo = db.work_orders.get(rec["work_order_id"])
        if wo is not None and wo["execution_status"] == "CLOSED":
            raise errors.invalid_state("Parent work order is already CLOSED.")
        rec["status"] = "RELEASED"
        db.touch(rec)
        part = db.spare_parts.get(rec["spare_part_id"])
        if part is not None:
            calc.recompute_reserved_qty(part)
        # If this was the WO's last non-RELEASED reservation, parts_status=RELEASED.
        if wo is not None:
            res = [r for r in db.part_reservations.values()
                   if r["work_order_id"] == wo["id"]]
            if res and all(r["status"] == "RELEASED" for r in res):
                wo["parts_status"] = "RELEASED"
                db.touch(wo)
        return object_response(serialize.part_reservation(rec), 200)

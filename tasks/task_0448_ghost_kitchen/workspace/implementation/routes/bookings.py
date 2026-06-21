"""EquipmentBooking endpoints (manual maintenance holds) (PRD §3.9)."""
from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import new_entity, touch, serialize, paginate, get_or_404
from services.scheduling import window_is_free
from validation import get_body, require_str, require_int

bp = Blueprint("bookings", __name__)


def _check_stall_owner(role, user_id, stall_id):
    if role == "StallOperator" and user_id != stall_id:
        raise errors.forbidden()


@bp.route("/equipment-bookings", methods=["POST"])
def create_booking():
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    body = get_body()
    equipment_id = require_str(body, "equipment_id")
    start_minute = require_int(body, "start_minute")
    end_minute = require_int(body, "end_minute")
    with store.lock:
        equipment = get_or_404(store.equipment, equipment_id)
        # Ownership: operator must own the equipment's stall.
        _check_stall_owner(role, user_id, equipment["stall_id"])
        # Booking overlap (priority 9) before field-shape (priority 12).
        # But field-shape of start/end ordering is a precondition for a valid
        # window; the half-open window requires start < end.
        if not (start_minute >= 0 and start_minute < end_minute):
            raise errors.invalid_request("Require 0 <= start_minute < end_minute.")
        if not window_is_free(equipment, start_minute, end_minute):
            raise errors.booking_overlap()
        rec = new_entity("EquipmentBooking", {
            "equipment_id": equipment_id,
            "order_id": None,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "status": "HELD",
        })
        store.bookings[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.route("/equipment-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator"])
    with store.lock:
        rec = get_or_404(store.bookings, bid)
        return object_response(serialize(rec))


@bp.route("/equipment-bookings", methods=["GET"])
def list_bookings():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator"])
    with store.lock:
        recs = list(store.bookings.values())
        order_id = request.args.get("order_id")
        if order_id is not None:
            recs = [b for b in recs if b["order_id"] == order_id]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)


@bp.route("/equipment-bookings/<bid>/release", methods=["POST"])
def release_booking(bid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.bookings, bid)
        # Only maintenance holds (order_id == null) may be released this way.
        # Ownership: operator must own the equipment's stall.
        equipment = store.equipment.get(rec["equipment_id"])
        if equipment is not None:
            _check_stall_owner(role, user_id, equipment["stall_id"])
        if rec["order_id"] is not None:
            # Order-driven bookings are not releasable via this endpoint.
            raise errors.forbidden()
        if rec["status"] != "HELD":
            raise errors.invalid_state()
        rec["status"] = "RELEASED"
        touch(rec)
        return object_response(serialize(rec))

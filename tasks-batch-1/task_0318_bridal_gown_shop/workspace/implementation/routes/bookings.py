"""FittingRoomBooking endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import common
import errors
import services
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")

bp = Blueprint("bookings", __name__)


def _peak_existing_coverage(room_id, cand_start, cand_end, exclude_id=None):
    """Max sum of HELD party_size over instants within [cand_start, cand_end).

    Half-open intervals: a booking ending exactly at cand_start does not overlap.
    Uses a boundary sweep — at each existing-interval start within the candidate
    window the running coverage is evaluated.
    """
    intervals = []
    for b in db.fitting_room_bookings.values():
        if b["id"] == exclude_id:
            continue
        if b["fitting_room_id"] != room_id:
            continue
        if b["status"] != "HELD":
            continue
        s = common.parse_iso_to_epoch(b["slot_start_at"])
        e = common.parse_iso_to_epoch(b["slot_end_at"])
        # Clip to the candidate window; skip non-overlapping (half-open).
        lo = max(s, cand_start)
        hi = min(e, cand_end)
        if lo < hi:
            intervals.append((lo, hi, b["party_size"]))
    if not intervals:
        return 0
    # Candidate instants of interest: each clipped interval start. Coverage is a
    # step function; its maxima occur at left endpoints.
    points = sorted({iv[0] for iv in intervals})
    peak = 0
    for t in points:
        coverage = sum(p for (lo, hi, p) in intervals if lo <= t < hi)
        if coverage > peak:
            peak = coverage
    return peak


@bp.route("/fitting-room-bookings", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def create_booking():
    body = common.get_body()
    # Existence: appointment_id FK first, then fitting_room_id (declaration order).
    appointment_id = common.as_str(body, "appointment_id")
    services.get_appointment(appointment_id)
    fitting_room_id = common.as_str(body, "fitting_room_id")
    room = services.get_fitting_room(fitting_room_id)
    party_size = common.as_int(body, "party_size", minimum=1)
    slot_start_at = common.parse_datetime_str(body, "slot_start_at")
    slot_end_at = common.parse_datetime_str(body, "slot_end_at")

    start_epoch = common.parse_iso_to_epoch(slot_start_at)
    end_epoch = common.parse_iso_to_epoch(slot_end_at)
    if not (end_epoch > start_epoch):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "slot_end_at must be strictly after slot_start_at")

    peak = _peak_existing_coverage(fitting_room_id, start_epoch, end_epoch)
    if peak + party_size > room["capacity"]:
        errors.raise_error(errors.ERR_FITTING_ROOM_OVERBOOKED, "Fitting room overbooked")

    obj = {
        "id": db.new_id(),
        "appointment_id": appointment_id,
        "fitting_room_id": fitting_room_id,
        "party_size": party_size,
        "slot_start_at": slot_start_at,
        "slot_end_at": slot_end_at,
        "status": "HELD",
    }
    db.stamp_create(obj)
    db.fitting_room_bookings[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/fitting-room-bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_bookings():
    limit, offset = common.paginate(request.args)
    rows = list(db.fitting_room_bookings.values())
    appointment_id = request.args.get("appointment_id")
    fitting_room_id = request.args.get("fitting_room_id")
    if appointment_id is not None:
        rows = [b for b in rows if b["appointment_id"] == appointment_id]
    if fitting_room_id is not None:
        rows = [b for b in rows if b["fitting_room_id"] == fitting_room_id]
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/fitting-room-bookings/<bid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_booking(bid):
    obj = services.get_booking(bid)
    return success(common.serialize(obj))


@bp.route("/fitting-room-bookings/<bid>/release", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def release_booking(bid):
    obj = services.get_booking(bid)
    if obj["status"] != "HELD":
        errors.raise_error(errors.ERR_BOOKING_NOT_HELD, "Booking is not HELD")
    obj["status"] = "RELEASED"
    db.touch(obj)
    return success(common.serialize(obj))

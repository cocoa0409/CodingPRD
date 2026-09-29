from datetime import datetime, timedelta, timezone

from flask import Blueprint

import find
import serialize
import services
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import db, new_record, sorted_records

bp = Blueprint("bookings", __name__)

ROLES = ["CorpsDirector", "TourManager", "MembershipCoordinator"]
BLOCK_BUFFER_MINUTES = 90
EXTREME_HEAT_INDEX = 105


def _midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


@bp.route("/site-bookings", methods=["POST"])
@endpoint(["TourManager"])
def create_booking():
    body = v.get_body()
    stop_id = v.req_str(body, "tour_stop_id")
    school_id = v.req_str(body, "host_school_id")
    agreement_id = v.req_str(body, "facility_agreement_id")
    start_raw, block_start = v.req_instant(body, "block_start_at")
    end_raw, block_end = v.req_instant(body, "block_end_at")
    indoor = v.req_bool(body, "indoor")
    # Rung 4 -- block_end_at must be later than block_start_at.
    v.date_range(block_end > block_start, "block_end_at must be later than block_start_at.")
    # Rung 8 -- stop, school, agreement, in declaration order.
    stop = find.stop(stop_id)
    school = find.school(school_id)
    agreement = find.agreement(agreement_id)
    # Rung 18 -- SIGNED agreement whose usage_type covers a rehearsal block.
    if agreement["status"] != "SIGNED" or agreement["usage_type"] != "TOUR_REHEARSAL":
        raise ApiError("ERR_AGREEMENT_NOT_SIGNED",
                       "A TOUR_REHEARSAL agreement in SIGNED status is required.")
    # Rung 20 -- the parent stop must be PLANNED or CONFIRMED.
    if stop["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STOP_STATE",
                       "The parent stop must be PLANNED or CONFIRMED.")
    # Rung 26 -- the stop's season must equal the agreement's season.
    if stop["season_id"] != agreement["season_id"]:
        raise ApiError("ERR_SEASON_MISMATCH",
                       "The stop's season does not match the agreement's season.")
    # Rung 28 -- the school must be the very school the agreement names.
    if agreement["host_school_id"] != school_id:
        raise ApiError("ERR_AGREEMENT_SCHOOL_MISMATCH",
                       "The agreement names a different host school.")
    # Rung 35 -- the extreme-heat protocol.
    if stop["heat_index_f"] >= EXTREME_HEAT_INDEX:
        if not indoor or not school["has_air_conditioning"]:
            raise ApiError("ERR_EXTREME_HEAT_OUTDOOR_PROHIBITED",
                           "Extreme heat permits only indoor blocks at air-conditioned schools.")
    # Rung 39 -- load-in and load-out buffers on both sides of every block.
    # Every block needs its own 90 minutes of load-in and load-out on both
    # sides, so two blocks at one school must be separated by a clear gap of at
    # least 180 minutes; exactly 180 is accepted because the comparison is
    # strict, and 179 is refused.
    buffer_delta = timedelta(minutes=2 * BLOCK_BUFFER_MINUTES)
    for other in db.bookings.values():
        if other["host_school_id"] != school_id:
            continue
        if other["status"] not in ("HELD", "CONFIRMED"):
            continue
        if (block_start < other["_block_end_at"] + buffer_delta
                and block_end > other["_block_start_at"] - buffer_delta):
            raise ApiError("ERR_SITE_BLOCK_CONFLICT",
                           "This block does not clear its neighbours' 180-minute gap.")
    # Rung 40 -- wholly inside the agreement's window, midnight to midnight.
    window_start = _midnight(agreement["_start_date"])
    window_end = _midnight(agreement["_end_date"])
    if block_start < window_start or block_end > window_end:
        raise ApiError("ERR_BLOCK_OUTSIDE_AGREEMENT_WINDOW",
                       "The block falls outside the agreement's window.")

    record = new_record()
    record.update({
        "tour_stop_id": stop_id,
        "host_school_id": school_id,
        "facility_agreement_id": agreement_id,
        "block_start_at": start_raw,
        "block_end_at": end_raw,
        "_block_start_at": block_start,
        "_block_end_at": block_end,
        "indoor": indoor,
        "status": "HELD",
        "released_reason": None,
    })
    db.bookings[record["id"]] = record
    return object_response(serialize.booking(record), 201)


@bp.route("/site-bookings/<site_booking_id>", methods=["GET"])
@endpoint(ROLES)
def get_booking(site_booking_id):
    return object_response(serialize.booking(find.booking(site_booking_id)))


@bp.route("/site-bookings", methods=["GET"])
@endpoint(ROLES)
def list_bookings():
    stop_id = v.arg_str("tour_stop_id")
    school_id = v.arg_str("host_school_id")
    agreement_id = v.arg_str("facility_agreement_id")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.bookings):
        if stop_id is not None and record["tour_stop_id"] != stop_id:
            continue
        if school_id is not None and record["host_school_id"] != school_id:
            continue
        if agreement_id is not None and record["facility_agreement_id"] != agreement_id:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.booking)


@bp.route("/site-bookings/<site_booking_id>/release", methods=["POST"])
@endpoint(["TourManager"])
def release_booking(site_booking_id):
    booking = find.booking(site_booking_id)
    # Rung 21 -- a release requires HELD or CONFIRMED.
    if booking["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE",
                       "Only a HELD or CONFIRMED block may be released.")
    services.release_booking(booking, "MANUAL")
    return object_response(serialize.booking(booking))

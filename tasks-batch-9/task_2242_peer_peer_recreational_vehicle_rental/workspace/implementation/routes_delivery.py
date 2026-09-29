"""Campground drop-off windows: scheduling, capacity fork and voiding."""

from flask import Blueprint

import calc
import enums
import serializers as ser
import services as svc
import validation as v
from envelope import list_response, object_response
from errors import fail
from store import creation_order, db, new_record, parse_date, parse_dt, touch
from web import paged, route

bp = Blueprint("delivery", __name__)


def _superseded_rows(booking_id):
    rows = [a for a in db.delivery_assignments.values()
            if a["booking_id"] == booking_id
            and a["status"] in ("REQUESTED", "SCHEDULED", "WAITLISTED")]
    return creation_order(rows)


@route(bp, "/delivery-assignments", ["POST"], ("Owner", "PlatformAdmin"))
def create_assignment(user_id, role):
    body = v.body()
    booking_id = v.get_str(body, "booking_id")
    campground_id = v.get_str(body, "campground_id")
    window_start = v.get_datetime(body, "window_start")
    window_end = v.get_datetime(body, "window_end")
    distance_miles = v.get_int(body, "distance_miles", 0, 500)
    setup_fee_cents = v.get_int(body, "setup_fee_cents", 0, 50000,
                                required=False, default=0)
    expected_booking_version = v.get_int(body, "expected_booking_version")

    booking = svc.lookup("bookings", booking_id)
    campground = svc.lookup("campgrounds", campground_id)
    svc.require_booking_access(role, user_id, booking)
    if expected_booking_version != booking["version"]:
        fail("ERR_STALE_PARENT_VERSION",
             "expected_booking_version does not match the booking's current version.")

    listing = svc.listing_of(booking)
    start = parse_dt(window_start)
    end = parse_dt(window_end)
    dropoff_date = start.date().isoformat()
    priors = _superseded_rows(booking_id)

    if svc.window_conflict(campground, start, end, dropoff_date,
                           exclude_ids=tuple(a["id"] for a in priors)):
        fail("ERR_DROPOFF_WINDOW_CONFLICT",
             "The window collides with an existing scheduled drop-off.")
    if end <= start or dropoff_date != booking["start_date"]:
        fail("ERR_INVALID_DATE_RANGE",
             "window_end must follow window_start and the window must fall on start_date.")
    if (listing["length_ft"] > campground["max_rig_length_ft"]
            or campground["status"] != "ACCEPTING"):
        fail("ERR_RIG_LENGTH_EXCEEDS_CAMPGROUND",
             "The rig does not fit this campground or the site is not accepting.")
    if booking["delivery_option"] != "CAMPGROUND_DROPOFF":
        fail("ERR_DELIVERY_NOT_APPLICABLE",
             "The booking is not a campground drop-off booking.")

    for prior in priors:
        svc.void_assignment(prior, zero_fee=True, touch_booking=False)
    if svc.window_conflict(campground, start, end, dropoff_date):
        fail("ERR_DROPOFF_WINDOW_CONFLICT",
             "The window collides with an existing scheduled drop-off.")

    assignment = new_record(
        booking_id=booking_id, campground_id=campground_id,
        window_start=window_start, window_end=window_end,
        distance_miles=distance_miles, setup_fee_cents=setup_fee_cents,
        delivery_fee_cents=calc.delivery_fee(listing, distance_miles, setup_fee_cents),
        status="REQUESTED", dropoff_date=dropoff_date,
        promoted_from_waitlist=False, void_reason=None,
        _window_start=start, _window_end=end)
    db.delivery_assignments[assignment["id"]] = assignment

    taken = len(svc.scheduled_on(campground_id, dropoff_date))
    if taken < campground["daily_dropoff_capacity"]:
        assignment["status"] = "SCHEDULED"
        svc.sync_campground_count(campground, +1)
        booking["delivery_fee_cents"] = assignment["delivery_fee_cents"]
        svc.recompute_quote_steps(booking)
    else:
        assignment["status"] = "WAITLISTED"
    touch(booking)
    return object_response(ser.dump("delivery_assignment", assignment), 201)


@route(bp, "/delivery-assignments/<assignment_id>", ["GET"],
       ("Owner", "Renter", "PlatformAdmin"))
def get_assignment(user_id, role, assignment_id):
    assignment = svc.lookup("delivery_assignments", assignment_id)
    return object_response(ser.dump("delivery_assignment", assignment))


@route(bp, "/delivery-assignments", ["GET"], ("Owner", "Renter", "PlatformAdmin"))
def list_assignments(user_id, role):
    limit, offset = v.pagination()
    booking_id = v.query_str("booking_id")
    campground_id = v.query_str("campground_id")
    status = v.query_enum("status", enums.ASSIGNMENT_STATUS)
    dropoff_date = v.query_date("dropoff_date")
    rows = creation_order(list(db.delivery_assignments.values()))
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if campground_id is not None:
        rows = [r for r in rows if r["campground_id"] == campground_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if dropoff_date is not None:
        rows = [r for r in rows if r["dropoff_date"] == dropoff_date]
    return list_response(ser.dump_all("delivery_assignment", paged(rows, limit, offset)),
                         limit, offset, len(rows))


@route(bp, "/delivery-assignments/<assignment_id>/void", ["POST"],
       ("Owner", "PlatformAdmin"))
def void_assignment_route(user_id, role, assignment_id):
    body = v.body()
    void_reason = v.get_str(body, "void_reason", min_len=1)
    assignment = svc.lookup("delivery_assignments", assignment_id)
    booking = db.bookings.get(assignment["booking_id"])
    if booking is not None:
        svc.require_booking_access(role, user_id, booking)
    if assignment["status"] not in ("SCHEDULED", "WAITLISTED"):
        fail("ERR_ASSIGNMENT_STATE_INVALID",
             "Only a SCHEDULED or WAITLISTED assignment may be voided.")
    svc.void_assignment(assignment, reason=void_reason, zero_fee=True,
                        touch_booking=False)
    return object_response(ser.dump("delivery_assignment", assignment))

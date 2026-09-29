"""Allocating play and closing it out (PRD 3.5, 3.6)."""

from datetime import timedelta

import calc
import derive
import errors
import middleware
import response
import validate
from db import bump, common_fields, db, new_id, now
from errors import ApiError
from routes.blueprint import bp
from routes.common import listing

FILTERS = {
    "field_id": "field_id",
    "requested_by_staff_member_id": "requested_by_staff_member_id",
    "activity_type": "activity_type",
    "status": "status",
}

_BUFFER = timedelta(minutes=calc.CHANGEOVER_BUFFER_MINUTES)


def _posture_gates(field, activity_type):
    """PRD 2.5: the two refusals are distinct and are not interchangeable."""
    if field["play_status"] not in ("OPEN", "RESTRICTED"):
        raise ApiError("ERR_FIELD_NOT_PLAYABLE", 422,
                       "A %s field accepts no allocation." % field["play_status"])
    if activity_type not in calc.ALLOWED_ACTIVITIES[field["play_status"]]:
        raise ApiError(
            "ERR_FIELD_RESTRICTED_FOR_ACTIVITY", 422,
            "A %s field will not take a %s." % (field["play_status"], activity_type))


@bp.post("/usage-bookings")
def create_booking():
    middleware.authenticate(["FieldOperationsCoordinator"])
    body = validate.Body(
        required=["field_id", "requested_by_staff_member_id", "activity_type",
                  "window_start_utc", "window_end_utc", "expected_participant_count"])

    field_id = body.string("field_id")
    staff_id = body.string("requested_by_staff_member_id")
    activity_type = body.enum("activity_type", calc.ACTIVITY_TYPES)
    start = body.instant("window_start_utc")
    end = body.instant("window_end_utc")
    expected = body.integer("expected_participant_count", 1, 500)

    field = middleware.body_field(field_id)          # priority 18
    middleware.body_staff(staff_id)                  # priority 19

    # priority 29 - the window rule
    if end.dt <= start.dt:
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "window_end_utc must be strictly after window_start_utc.")

    # priority 34 - the retirement guard
    if field["retired_at"] is not None:
        raise ApiError("ERR_FIELD_RETIRED", 409,
                       "A retired field accepts no allocation.")

    # priorities 51 and 52 - the posture and activity gates
    _posture_gates(field, activity_type)

    # priority 62 - INTERVAL SEMANTICS A: symmetric thirty-minute changeover buffer
    for other in db.usage_bookings.values():
        if (other["field_id"] == field_id
                and other["status"] in ("SCHEDULED", "CONFIRMED")
                and start.dt < other["window_end_utc"].dt + _BUFFER
                and other["window_start_utc"].dt < end.dt + _BUFFER):
            raise ApiError("ERR_BOOKING_WINDOW_CONFLICT", 409,
                           "The requested window collides with an existing booking "
                           "once the changeover buffer is applied.")

    booking = {
        "id": new_id(),
        "field_id": field_id,
        "requested_by_staff_member_id": staff_id,
        "activity_type": activity_type,
        "window_start_utc": start,
        "window_end_utc": end,
        "expected_participant_count": expected,
        "status": "SCHEDULED",
        "started_with_rest_debt": None,
        "confirmed_at_utc": None,
        "outcome": None,
        "actual_duration_hours": None,
        "actual_participant_count": None,
        "weather_condition": None,
        "wear_load_units": None,
        "rest_requirement_hours": None,
        "closed_out_at_utc": None,
    }
    booking.update(common_fields())
    db.usage_bookings[booking["id"]] = booking
    return response.created(booking)


@bp.get("/usage-bookings")
def list_bookings():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.usage_bookings, FILTERS)


@bp.get("/usage-bookings/<booking_id>")
def read_booking(booking_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.booking_or_404(booking_id))


@bp.post("/usage-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    middleware.authenticate(["FieldOperationsCoordinator"])
    booking = middleware.booking_or_404(booking_id)
    validate.Body()

    # priority 39 - the booking must still be SCHEDULED
    if booking["status"] != "SCHEDULED":
        raise ApiError("ERR_BOOKING_NOT_SCHEDULED", 409,
                       "Only a SCHEDULED booking may be confirmed.")

    field = db.fields[booking["field_id"]]

    # priorities 51 and 52 - the gates are re-run against the world as it now stands
    _posture_gates(field, booking["activity_type"])

    # priority 59 - the tournament certification gate applies only here
    if (booking["activity_type"] == "TOURNAMENT"
            and field["sanctioned_level"] != "NONE"
            and field["certification_status"] != "CERTIFIED"):
        raise ApiError("ERR_FIELD_NOT_CERTIFIED", 422,
                       "A sanctioned field must be CERTIFIED to host a TOURNAMENT.")

    # priority 60 - confirmation must happen before play starts
    current = now()
    if current.dt >= booking["window_start_utc"].dt:
        raise ApiError("ERR_BOOKING_WINDOW_STARTED", 422,
                       "The booking window has already started.")

    booking["status"] = "CONFIRMED"
    booking["confirmed_at_utc"] = current
    booking["started_with_rest_debt"] = field["rest_debt_hours"] > calc.ZERO
    bump(booking)
    return response.ok(booking)


@bp.post("/usage-bookings/<booking_id>/close-out")
def close_out_booking(booking_id):
    middleware.authenticate(["FieldOperationsCoordinator"])
    booking = middleware.booking_or_404(booking_id)
    body = validate.Body(required=["outcome", "actual_duration_hours",
                                   "actual_participant_count", "weather_condition"])
    outcome = body.enum("outcome", calc.CLOSE_OUT_OUTCOMES)
    duration = body.number("actual_duration_hours", calc.ZERO)
    participants = body.integer("actual_participant_count", 0)
    weather = body.enum("weather_condition", calc.WEATHER_CONDITIONS)

    # priority 40 - the booking must be CONFIRMED
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_BOOKING_NOT_CONFIRMED", 409,
                       "Only a CONFIRMED booking may be closed out.")

    # priority 61 - the window must already have elapsed
    current = now()
    if current.dt < booking["window_end_utc"].dt:
        raise ApiError("ERR_BOOKING_WINDOW_NOT_ELAPSED", 422,
                       "The booking window has not yet elapsed.")

    # PRD 3.6: each outcome carries its own consistency requirement
    if outcome == "PLAYED" and duration <= calc.ZERO:
        raise errors.invalid_request(
            "A PLAYED outcome requires actual_duration_hours greater than 0.00.")
    if outcome == "CANCELLED_LATE" and duration != calc.ZERO:
        raise errors.invalid_request(
            "A CANCELLED_LATE outcome requires actual_duration_hours of exactly 0.00.")
    if outcome == "RAINED_OUT" and weather != "WET":
        raise errors.invalid_request(
            "A RAINED_OUT outcome requires weather_condition WET.")

    field = db.fields[booking["field_id"]]
    wear = calc.wear_load_units(
        outcome, booking["activity_type"], field["surface_type"], weather,
        booking["window_start_utc"], booking["window_end_utc"],
        duration, participants, booking["expected_participant_count"])
    if outcome == "CANCELLED_LATE":
        rest = calc.r2(calc.ZERO)
    else:
        rest = calc.rest_requirement_hours(wear, field["surface_type"], weather)

    booking["outcome"] = outcome
    booking["status"] = outcome
    booking["actual_duration_hours"] = calc.r2(duration)
    booking["actual_participant_count"] = participants
    booking["weather_condition"] = weather
    booking["wear_load_units"] = wear
    booking["rest_requirement_hours"] = rest
    booking["closed_out_at_utc"] = current
    bump(booking)

    if outcome == "CANCELLED_LATE":
        derive.append_ledger(field, "LATE_CANCEL_WEAR", wear,
                             rest_requirement_hours=calc.ZERO,
                             rest_window_end_utc=None,
                             booking_id=booking["id"],
                             note="BOOKING_CLOSED_OUT_CANCELLED_LATE")
    else:
        rest_window_end = booking["window_end_utc"].plus_hours(rest)
        derive.append_ledger(field, "PLAY_WEAR", wear,
                             rest_requirement_hours=rest,
                             rest_window_end_utc=rest_window_end,
                             booking_id=booking["id"],
                             note="BOOKING_CLOSED_OUT_%s" % outcome)
        if outcome == "RAINED_OUT":
            # PRD 2.9: the exact negative counterpart, so the pair sums to 0.00.
            derive.append_ledger(field, "RAIN_OUT_RELIEF", -wear,
                                 rest_requirement_hours=calc.ZERO,
                                 rest_credit_hours=calc.ZERO,
                                 rest_window_end_utc=None,
                                 booking_id=booking["id"],
                                 note="BOOKING_CLOSED_OUT_RAINED_OUT_RELIEF")

    derive.touch_field(field)
    return response.ok(booking)

"""CrewBooking endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import factory

bp = Blueprint("crew_bookings", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intervals intersect iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


@bp.route("/crew-bookings", methods=["POST"])
def create_booking():
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    body = get_json_body()
    # body FK check (priority 4): crew_id, install_order_id.
    helpers.require_fields(body, ["crew_id", "install_order_id"])
    helpers.fk_or_422(db.crews, body["crew_id"], "Crew")
    helpers.fk_or_422(db.install_orders, body["install_order_id"], "InstallOrder")

    window_start = helpers.require_datetime(body, "window_start")
    window_end = helpers.require_datetime(body, "window_end")

    entity = factory.create_crew_booking(
        body["crew_id"], body["install_order_id"],
        helpers.iso_from_dt(window_start), helpers.iso_from_dt(window_end),
    )
    return object_response(serialize(entity), status=201)


@bp.route("/crew-bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    entity = helpers.find_or_404(db.crew_bookings, booking_id)
    return object_response(serialize(entity), status=200)


@bp.route("/crew-bookings", methods=["GET"])
def list_bookings():
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    limit, offset = get_pagination()
    crew_id = request.args.get("crew_id")
    install_order_id = request.args.get("install_order_id")
    status = request.args.get("status")

    def pred(b):
        if crew_id is not None and b["crew_id"] != crew_id:
            return False
        if install_order_id is not None and b["install_order_id"] != install_order_id:
            return False
        if status is not None and b["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.crew_bookings, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/crew-bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    booking = helpers.find_or_404(db.crew_bookings, booking_id)
    # state: RESERVED (PRD §3.8).
    if booking["status"] != "RESERVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a RESERVED booking can be confirmed")

    start = helpers.parse_iso(booking["window_start"])
    end = helpers.parse_iso(booking["window_end"])
    crew_id = booking["crew_id"]

    # priority 14: overlap with another CONFIRMED booking on the same crew.
    for b in db.crew_bookings.items.values():
        if b["id"] == booking_id:
            continue
        if b["crew_id"] != crew_id or b["status"] != "CONFIRMED":
            continue
        if _overlaps(start, end, helpers.parse_iso(b["window_start"]), helpers.parse_iso(b["window_end"])):
            raise errors.err(errors.ERR_CREW_DOUBLE_BOOKED, "Booking overlaps an existing CONFIRMED window")

    # priority 15: daily capacity for the booking's calendar day.
    booking_day = start.date()
    same_day_confirmed = 0
    for b in db.crew_bookings.items.values():
        if b["id"] == booking_id:
            continue
        if b["crew_id"] != crew_id or b["status"] != "CONFIRMED":
            continue
        if helpers.parse_iso(b["window_start"]).date() == booking_day:
            same_day_confirmed += 1
    crew = db.crews.items.get(crew_id)
    if same_day_confirmed >= crew["daily_capacity"]:
        raise errors.err(errors.ERR_CREW_CAPACITY_EXCEEDED, "Confirming would exceed the crew's daily capacity")

    booking["status"] = "CONFIRMED"
    helpers.touch(booking)
    return object_response(serialize(booking), status=200)


@bp.route("/crew-bookings/<booking_id>/release", methods=["POST"])
def release_booking(booking_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    booking = helpers.find_or_404(db.crew_bookings, booking_id)
    if booking["status"] not in ("RESERVED", "CONFIRMED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Only a RESERVED or CONFIRMED booking can be released")
    booking["status"] = "RELEASED"
    helpers.touch(booking)
    return object_response(serialize(booking), status=200)

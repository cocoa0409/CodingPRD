"""Booking routes (PRD §3.4)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_WINDOW_CLOSED,
    ERR_BOOKING_OVERLAP,
    ERR_ARTIST_MISMATCH,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_string,
    check_int,
    check_date_string,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from routes.bays import get_bay_or_404
from services.transitions import guard_transition
from clock import clock as logical_clock

bp = Blueprint("bookings", __name__)

BOOKING_TERMINAL = ("COMPLETED", "CANCELLED", "NO_SHOW")
LIST_ROLES = ("PostSupervisor", "ConformEditor", "Artist")


def serialize(booking):
    return dict(booking)


def get_booking_or_404(project, booking_id):
    booking = db.bookings.get(booking_id)
    if booking is None or booking["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"Booking {booking_id} does not exist", 404)
    return booking


@bp.route("/post-production/projects/<project_id>/bookings", methods=["POST"])
def create_booking(project_id):
    user_id, role = require_roles(("PostSupervisor", "Artist"))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(
        body,
        (
            "bay_id",
            "artist_email",
            "session_date",
            "start_hour",
            "end_hour",
            "version_tag",
            "expected_bay_version",
        ),
    )
    bay_id = body["bay_id"]
    if not isinstance(bay_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'bay_id' must be a string", 400)
    # FK resolution (priority 3)
    bay = db.edit_bays.get(bay_id)
    if bay is None or bay["project_id"] != project_id:
        raise ApiError(ERR_NOT_FOUND, f"EditBay {bay_id} does not exist", 404)
    # Body shape (priority 4)
    artist_email = check_string(body, "artist_email")
    if artist_email != artist_email.lower():
        raise ApiError(
            ERR_INVALID_REQUEST, "Field 'artist_email' must be lowercase", 400
        )
    session_date = check_date_string(body, "session_date")
    start_hour = check_int(body, "start_hour", min_v=0, max_v=23)
    end_hour = check_int(body, "end_hour", min_v=1, max_v=24)
    if end_hour <= start_hour:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'end_hour' must be strictly greater than 'start_hour'",
            400,
        )
    check_string(body, "version_tag")
    expected_bay_version = body["expected_bay_version"]
    if not isinstance(expected_bay_version, int) or isinstance(
        expected_bay_version, bool
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'expected_bay_version' must be an integer",
            400,
        )
    # Stale-version guard (priority 5)
    if expected_bay_version != bay["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_bay_version does not match the bay's current version",
            412,
        )
    # Temporal window (priority 7): session_date must be today or future.
    today = logical_clock.now().date().isoformat()
    if session_date < today:
        raise ApiError(
            ERR_WINDOW_CLOSED,
            "Booking session_date must be the present day or a future day",
            422,
        )
    # Booking overlap (priority 8): half-open interval semantics.
    for other in db.bookings.values():
        if other.get("bay_id") != bay_id:
            continue
        if other["session_date"] != session_date:
            continue
        if other["status"] in BOOKING_TERMINAL:
            continue
        # Half-open: touching intervals (end == other.start) do not conflict.
        if start_hour < other["end_hour"] and other["start_hour"] < end_hour:
            raise ApiError(
                ERR_BOOKING_OVERLAP,
                "Requested hour interval overlaps an existing non-terminal "
                "Booking for the same bay and session_date",
                409,
            )
    booking = new_entity(
        {
            "project_id": project_id,
            "bay_id": bay_id,
            "artist_email": artist_email,
            "session_date": session_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "version_tag": body["version_tag"],
            "status": "RESERVED",
            "booked_hours": end_hour - start_hour,
        }
    )
    db.bookings[booking["id"]] = booking
    # Creating a booking increments the bay's version (PRD §3.4, endpoint
    # side effects).
    touch(bay)
    return success_object(serialize(booking), 201)


@bp.route("/post-production/projects/<project_id>/bookings", methods=["GET"])
def list_bookings(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [b for b in db.bookings.values() if b["project_id"] == project_id]
    bay_id = get_filter("bay_id")
    if bay_id is not None:
        items = [b for b in items if b.get("bay_id") == bay_id]
    session_date = get_filter("session_date")
    if session_date is not None:
        items = [b for b in items if b["session_date"] == session_date]
    status = get_filter("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/bookings/<booking_id>", methods=["GET"]
)
def get_booking(project_id, booking_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    booking = get_booking_or_404(project, booking_id)
    return success_object(serialize(booking))


def _artist_matches(user_id, booking):
    return user_id.lower() == booking["artist_email"].lower()


@bp.route(
    "/post-production/projects/<project_id>/bookings/<booking_id>/check-in",
    methods=["POST"],
)
def check_in_booking(project_id, booking_id):
    user_id, role = require_roles(("Artist",))
    project = get_project_or_404(project_id)
    booking = get_booking_or_404(project, booking_id)
    guard_transition(booking, "RESERVED", BOOKING_TERMINAL, "booking")
    # Temporal window (priority 7): session_date == today and current hour in
    # [start_hour, end_hour).
    now = logical_clock.now()
    today = now.date().isoformat()
    if booking["session_date"] != today:
        raise ApiError(
            ERR_WINDOW_CLOSED,
            "Check-in requires session_date to equal the current logical date",
            422,
        )
    if not (booking["start_hour"] <= now.hour < booking["end_hour"]):
        raise ApiError(
            ERR_WINDOW_CLOSED,
            "Check-in requires the current logical hour to be at least "
            "start_hour and before end_hour",
            422,
        )
    # Artist identity (priority 18)
    if not _artist_matches(user_id, booking):
        raise ApiError(
            ERR_ARTIST_MISMATCH,
            "X-User-ID does not match Booking.artist_email on check-in",
            403,
        )
    booking["status"] = "CHECKED_IN"
    touch(booking)
    return success_object(serialize(booking))


@bp.route(
    "/post-production/projects/<project_id>/bookings/<booking_id>/complete",
    methods=["POST"],
)
def complete_booking(project_id, booking_id):
    user_id, role = require_roles(("Artist",))
    project = get_project_or_404(project_id)
    booking = get_booking_or_404(project, booking_id)
    guard_transition(booking, "CHECKED_IN", BOOKING_TERMINAL, "booking")
    if not _artist_matches(user_id, booking):
        raise ApiError(
            ERR_ARTIST_MISMATCH,
            "X-User-ID does not match Booking.artist_email on complete",
            403,
        )
    booking["status"] = "COMPLETED"
    touch(booking)
    return success_object(serialize(booking))


@bp.route(
    "/post-production/projects/<project_id>/bookings/<booking_id>/cancel",
    methods=["POST"],
)
def cancel_booking(project_id, booking_id):
    user_id, role = require_roles(("PostSupervisor", "Artist"))
    project = get_project_or_404(project_id)
    booking = get_booking_or_404(project, booking_id)
    guard_transition(booking, "RESERVED", BOOKING_TERMINAL, "booking")
    if role == "Artist":
        # Artist may cancel only their own booking and only while its
        # session_date lies strictly after the current logical date.
        if not _artist_matches(user_id, booking):
            raise ApiError(
                ERR_ARTIST_MISMATCH,
                "X-User-ID does not match Booking.artist_email on "
                "artist-initiated cancellation",
                403,
            )
        today = logical_clock.now().date().isoformat()
        if booking["session_date"] <= today:
            raise ApiError(
                ERR_INVALID_STATE,
                "An Artist may cancel only bookings whose session_date lies "
                "strictly after the current logical date",
                409,
            )
    booking["status"] = "CANCELLED"
    touch(booking)
    return success_object(serialize(booking))


# ---------------------------------------------------------------------------
# Flat alias
# ---------------------------------------------------------------------------


@bp.route("/post-production/bookings/<booking_id>", methods=["GET"])
def get_booking_flat(booking_id):
    require_roles(LIST_ROLES)
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise ApiError(ERR_NOT_FOUND, f"Booking {booking_id} does not exist", 404)
    return success_object(serialize(booking))

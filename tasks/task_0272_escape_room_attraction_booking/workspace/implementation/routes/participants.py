from flask import Blueprint, request

import errors
from errors import err
from db import db
from middleware import require_roles, get_json
from response import ok, listing
from services import validate as V
from services.entities import (
    get_participant, get_booking, get_room, ser_participant, touch,
)

bp = Blueprint("participants", __name__)


def _customer_owns_participant(user_id, role, participant):
    if role == "Customer":
        booking = db.bookings.get(participant["booking_id"])
        if booking is None or user_id != booking["customer_id"]:
            raise err(errors.ERR_FORBIDDEN, "Customer does not own this participant")


@bp.get("/participants/<participant_id>")
def read_participant(participant_id):
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    p = get_participant(participant_id)
    return ok(ser_participant(p))


@bp.get("/participants")
def list_participants():
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    limit, offset = V.parse_pagination()
    booking_id = request.args.get("booking_id")
    rows = list(db.participants.values())
    if booking_id is not None:
        rows = [p for p in rows if p["booking_id"] == booking_id]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_participant(p) for p in page], limit, offset, total)


@bp.post("/participants/<participant_id>/sign-waiver")
def sign_waiver(participant_id):
    user_id, role = require_roles({"Customer"})
    p = get_participant(participant_id)
    _customer_owns_participant(user_id, role, p)
    body = get_json()
    expected = V.req_int(body, "expected_participant_version")

    booking = get_booking(p["booking_id"])
    # State: waiver_status in {PENDING, REVOKED}; booking in DRAFT/CONFIRMED.
    if booking["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "Booking not in DRAFT/CONFIRMED")
    if p["waiver_status"] not in ("PENDING", "REVOKED"):
        raise err(errors.ERR_INVALID_STATE, "Waiver not in PENDING/REVOKED")
    if expected != p["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale participant version")

    # Age requirement.
    room = get_room(booking["room_id"])
    if p["age"] < room["min_age"]:
        raise err(errors.ERR_AGE_REQUIREMENT_NOT_MET, "Participant under room min_age")

    p["waiver_status"] = "SIGNED"
    touch(p)
    return ok(ser_participant(p))


@bp.post("/participants/<participant_id>/revoke-waiver")
def revoke_waiver(participant_id):
    user_id, role = require_roles({"Customer"})
    p = get_participant(participant_id)
    _customer_owns_participant(user_id, role, p)
    body = get_json()
    expected = V.req_int(body, "expected_participant_version")

    booking = get_booking(p["booking_id"])
    if booking["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "Booking not in DRAFT/CONFIRMED")
    if p["waiver_status"] != "SIGNED":
        raise err(errors.ERR_INVALID_STATE, "Waiver not SIGNED")
    if expected != p["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale participant version")

    p["waiver_status"] = "REVOKED"
    touch(p)
    return ok(ser_participant(p))


@bp.post("/participants/<participant_id>/mark-present")
def mark_present(participant_id):
    require_roles({"GameMaster"})
    p = get_participant(participant_id)
    body = get_json()
    expected = V.req_int(body, "expected_participant_version")
    if expected != p["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale participant version")
    p["checked_in"] = True
    touch(p)
    return ok(ser_participant(p))

"""Roster management: participants, screening packets and medical clearance."""
from flask import Blueprint, g

from db import store, base_row, touch, by_created_at
from errors import ApiError, invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_bool, req_num, req_int, req_date, req_str_list
from services import constants as C
from services import derive, serialize
from services.lookup import get_booking, get_participant, apply_filters

bp = Blueprint("participants", __name__)
PREFIX = "/challenge-course"

READ_ROLES = ["ProgramDirector", "SafetyOfficer", "Facilitator", "GroupCoordinator"]


def _screening_of(row):
    booking = store.bookings.get(row["booking_id"])
    return derive.screening_status(row, booking) if booking else None


@bp.post(PREFIX + "/participants")
def create_participant():
    authorize(["GroupCoordinator"])
    payload = body()

    booking_id = req_str(payload, "booking_id")
    expected_version = req_int(payload, "expected_booking_version", minimum=0)
    full_name = req_str(payload, "full_name")
    birth_date = req_date(payload, "birth_date")
    weight_kg = req_num(payload, "weight_kg", exclusive_min=0)
    is_chaperone = req_bool(payload, "is_chaperone", required=False, default=False)

    booking = get_booking(booking_id)

    # Step 7 — the roster belongs to the booking's own coordinator.
    if booking["group_client_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Step 8 — optimistic concurrency on the owning booking.
    if booking["version"] != expected_version:
        raise ApiError("ERR_STALE_BOOKING_VERSION")

    # Step 9.
    if booking["status"] in C.TERMINAL_BOOKING_STATUSES:
        raise ApiError("ERR_BOOKING_ALREADY_TERMINAL")

    row = base_row()
    row.update({
        "booking_id": booking["id"],
        "full_name": full_name,
        "birth_date": birth_date,
        "weight_kg": weight_kg,
        "is_chaperone": is_chaperone,
        "health_form_status": "MISSING",
        "health_flags": [],
        "agreement_signed": False,
        "guardian_signature_provided": False,
        "medical_clearance_granted": False,
    })
    store.participants[row["id"]] = row

    # Every roster write increments the owning booking's version.
    touch(booking)
    return created_response(serialize.participant(row))


@bp.get(PREFIX + "/participants/<participant_id>")
def read_participant(participant_id):
    authorize(READ_ROLES)
    row = get_participant(participant_id)
    return object_response(serialize.participant(row))


@bp.get(PREFIX + "/participants")
def list_participants():
    authorize(READ_ROLES)
    limit, offset = pagination()
    rows = by_created_at(list(store.participants.values()))
    rows = apply_filters(rows, {
        "booking_id": ("str", "booking_id"),
        "screening_status": ("str", "screening_status"),
        "health_form_status": ("str", "health_form_status"),
        "is_chaperone": ("bool", "is_chaperone"),
    }, accessors={"screening_status": _screening_of})
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.participant(r) for r in window], limit, offset, total)


@bp.post(PREFIX + "/participants/<participant_id>/screening-packet")
def submit_screening_packet(participant_id):
    authorize(["GroupCoordinator"])
    payload = body()

    agreement_signed = req_bool(payload, "agreement_signed")
    guardian_signature_provided = req_bool(payload, "guardian_signature_provided")
    health_flags = req_str_list(payload, "health_flags", C.HEALTH_FLAGS,
                                required=False, default=[])

    # Step 4 — an unsigned agreement is not a packet at all.
    if not agreement_signed:
        raise invalid("agreement_signed must be true.")

    participant = get_participant(participant_id)
    booking = store.bookings.get(participant["booking_id"])

    # Step 7.
    if booking is None or booking["group_client_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Step 9.
    if booking["status"] in C.TERMINAL_BOOKING_STATUSES:
        raise ApiError("ERR_BOOKING_ALREADY_TERMINAL")

    blocking = [f for f in health_flags if f in C.BLOCKING_HEALTH_FLAGS]

    participant["health_flags"] = list(health_flags)
    participant["agreement_signed"] = True
    participant["guardian_signature_provided"] = guardian_signature_provided
    if blocking:
        participant["health_form_status"] = "FLAGGED"
        # A clearance granted against older information may not be reused.
        participant["medical_clearance_granted"] = False
    else:
        participant["health_form_status"] = "SUBMITTED"
    touch(participant)
    touch(booking)

    return object_response(serialize.participant(participant))


@bp.post(PREFIX + "/participants/<participant_id>/medical-clearance")
def grant_medical_clearance(participant_id):
    authorize(["SafetyOfficer"])
    payload = body()
    req_str(payload, "clearance_note")

    participant = get_participant(participant_id)

    # Step 9 — only a flagged form can be cleared.
    if participant["health_form_status"] != "FLAGGED":
        raise ApiError("ERR_INVALID_STATE")

    booking = store.bookings.get(participant["booking_id"])
    if booking is not None and booking["status"] in C.TERMINAL_BOOKING_STATUSES:
        raise ApiError("ERR_BOOKING_ALREADY_TERMINAL")

    participant["health_form_status"] = "CLEARED"
    participant["medical_clearance_granted"] = True
    touch(participant)
    if booking is not None:
        touch(booking)

    return object_response(serialize.participant(participant))

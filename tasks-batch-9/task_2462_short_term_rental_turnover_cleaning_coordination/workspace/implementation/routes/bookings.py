"""The booking calendar: import, courtesies, departure, cancellation, reviews."""

from datetime import timedelta

from flask import Blueprint

import errors
import validation as v
from db import base_fields, db, now, ordered, touch
from errors import fail
from middleware import authenticate
from response import created, ok, ok_list
from services import lookup
from services.cascade import block_incoming_gate, void_turnover
from services.listing import sort_bookings
from services.serialize import booking_view
from services.window import (
    MAX_LATE_CHECKOUT_MINUTES,
    apply_window,
    is_non_terminal,
    preview_recompute,
    turnover_boundaries,
)

bp = Blueprint("bookings", __name__)

BOOKING_STATUSES = ("SCHEDULED", "CHECKED_OUT", "CANCELLED")
CHECKIN_GATES = ("OPEN", "BLOCKED", "RELEASED")
CHANGE_TYPES = ("LATE_CHECKOUT", "EARLY_CHECKIN")
OCCUPYING_STATUSES = ("SCHEDULED", "CHECKED_OUT")


def _outgoing_turnovers(booking_id):
    return [t for t in ordered(db.turnovers.values())
            if t["outgoing_booking_id"] == booking_id and is_non_terminal(t)]


def _incoming_turnovers(booking_id):
    return [t for t in ordered(db.turnovers.values())
            if t.get("incoming_booking_id") == booking_id and is_non_terminal(t)]


def _preview_with(turnover, booking_override):
    """The window this turnover would derive if `booking_override` replaced its
    matching boundary booking."""
    prop = db.properties[turnover["property_id"]]
    outgoing, incoming = turnover_boundaries(turnover)
    if outgoing["id"] == booking_override["id"]:
        outgoing = booking_override
    if incoming is not None and incoming["id"] == booking_override["id"]:
        incoming = booking_override
    return preview_recompute(turnover, prop, outgoing, incoming, incoming_is_set=True)


@bp.post("/bookings")
def create_booking():
    authenticate(("Coordinator",))
    body = v.json_body()
    property_id = v.req_string(body, "property_id", allow_empty=False)
    external_ref = v.req_string(body, "external_ref", allow_empty=False)
    guest_name = v.req_string(body, "guest_name", allow_empty=False)
    checkin_at = v.req_datetime(body, "checkin_at")
    checkout_at = v.req_datetime(body, "checkout_at")
    party_size = v.opt_int(body, "party_size", 1, minimum=1, maximum=24)
    pet_stay = v.opt_bool(body, "pet_stay", False)

    prop = lookup.get_property(property_id)

    if checkout_at <= checkin_at:
        fail(errors.ERR_INVALID_TIME_INTERVAL,
             "checkout_at must be strictly later than checkin_at.")

    # Half-open occupancy, zero buffer, contracted checkout only (PRD 2.6).
    for existing in db.bookings.values():
        if existing["property_id"] != prop["id"]:
            continue
        if existing["status"] not in OCCUPYING_STATUSES:
            continue
        if checkin_at < existing["checkout_at"] and existing["checkin_at"] < checkout_at:
            fail(errors.ERR_BOOKING_OVERLAP,
                 "The occupancy interval overlaps an existing stay on this property.")

    for existing in db.bookings.values():
        if existing["property_id"] == prop["id"] and existing["external_ref"] == external_ref:
            fail(errors.ERR_DUPLICATE_RESOURCE_KEY,
                 "external_ref '%s' already exists on this property." % external_ref)

    record = base_fields()
    record.update({
        "property_id": prop["id"],
        "external_ref": external_ref,
        "guest_name": guest_name,
        "party_size": party_size,
        "pet_stay": pet_stay,
        "checkin_at": checkin_at,
        "checkout_at": checkout_at,
        "late_checkout_until_at": None,
        "early_checkin_at": None,
        "actual_checkout_at": None,
        "status": "SCHEDULED",
        "checkin_gate": "OPEN",
        "guest_notice_code": "NONE",
        "cleanliness_rating": None,
        "cleanliness_rated_at": None,
    })
    db.bookings[record["id"]] = record
    return created(booking_view(record))


@bp.get("/bookings")
def list_bookings():
    actor = authenticate(("PlatformAdmin", "Coordinator", "PropertyOwner"))
    limit, offset = v.pagination()
    property_id = v.query_string("property_id")
    status = v.query_enum("status", BOOKING_STATUSES)
    checkin_gate = v.query_enum("checkin_gate", CHECKIN_GATES)

    lookup.owner_scope_list(actor, property_id)

    rows = list(db.bookings.values())
    if property_id is not None:
        rows = [b for b in rows if b["property_id"] == property_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    if checkin_gate is not None:
        rows = [b for b in rows if b["checkin_gate"] == checkin_gate]
    rows = sort_bookings(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([booking_view(r) for r in page], limit, offset, total)


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "PropertyOwner"))
    booking = lookup.get_booking(booking_id)
    lookup.owner_scope_resource(actor, booking["property_id"])
    return ok(booking_view(booking))


@bp.post("/bookings/<booking_id>/schedule-change")
def schedule_change(booking_id):
    authenticate(("Coordinator",))
    body = v.json_body()
    change_type = v.req_enum(body, "change_type", CHANGE_TYPES)
    new_time_at = v.req_datetime(body, "new_time_at")
    override_reason = v.opt_string(body, "override_reason")

    booking = lookup.get_booking(booking_id)
    if booking["status"] != "SCHEDULED":
        fail(errors.ERR_BOOKING_NOT_SCHEDULED,
             "A schedule change requires the stay to still be SCHEDULED.")

    if change_type == "LATE_CHECKOUT":
        affected = _outgoing_turnovers(booking["id"])
        if new_time_at <= booking["checkout_at"]:
            fail(errors.ERR_INVALID_TIME_INTERVAL,
                 "A late checkout must fall strictly later than the contracted checkout.")
        if new_time_at > booking["checkout_at"] + timedelta(minutes=MAX_LATE_CHECKOUT_MINUTES):
            fail(errors.ERR_SCHEDULE_CHANGE_LIMIT_EXCEEDED,
                 "A late checkout may not fall more than 240 minutes past the contracted checkout.")
        candidate = dict(booking)
        candidate["late_checkout_until_at"] = new_time_at
    else:
        affected = _incoming_turnovers(booking["id"])
        if new_time_at >= booking["checkin_at"]:
            fail(errors.ERR_INVALID_TIME_INTERVAL,
                 "An early check-in must fall strictly earlier than the contracted check-in.")
        for turnover in affected:
            if new_time_at < turnover["window_start_at"]:
                fail(errors.ERR_INVALID_TIME_INTERVAL,
                     "An early check-in may not fall before the turnover's window_start_at.")
        candidate = dict(booking)
        candidate["early_checkin_at"] = new_time_at

    derivations = []
    for turnover in affected:
        derived = _preview_with(turnover, candidate)
        if derived["raw_window_minutes"] <= 0:
            fail(errors.ERR_CLEANING_WINDOW_NON_POSITIVE,
                 "The derived cleaning window would not be strictly positive.")
        if derived["window_minutes"] < derived["required_minutes"] and not override_reason:
            fail(errors.ERR_SCHEDULE_CHANGE_BLOCKS_TURN,
                 "The change would compress the cleaning window below required_minutes.")
        derivations.append((turnover, derived))

    override_was_required = any(
        d["window_minutes"] < d["required_minutes"] for _, d in derivations)

    if change_type == "LATE_CHECKOUT":
        booking["late_checkout_until_at"] = new_time_at
        booking["guest_notice_code"] = "LATE_CHECKOUT_GRANTED"
    else:
        booking["early_checkin_at"] = new_time_at
        if override_was_required and override_reason:
            booking["guest_notice_code"] = "EARLY_CHECKIN_LIMITED"
    touch(booking)

    for turnover, derived in derivations:
        apply_window(turnover, derived)
        touch(turnover)

    return ok(booking_view(booking))


@bp.post("/bookings/<booking_id>/checkout")
def record_checkout(booking_id):
    authenticate(("Coordinator",))
    body = v.json_body()
    actual_checkout_at = v.opt_datetime(body, "actual_checkout_at")

    booking = lookup.get_booking(booking_id)
    if booking["status"] != "SCHEDULED":
        fail(errors.ERR_BOOKING_NOT_SCHEDULED,
             "Recording a departure requires the stay to be SCHEDULED.")

    booking["actual_checkout_at"] = actual_checkout_at if actual_checkout_at else now()
    booking["status"] = "CHECKED_OUT"
    touch(booking)

    # This boundary movement never refuses: the window is clamped, not rejected.
    for turnover in _outgoing_turnovers(booking["id"]):
        derived = _preview_with(turnover, booking)
        apply_window(turnover, derived)
        touch(turnover)
        if turnover["window_minutes"] == 0:
            block_incoming_gate(turnover)

    return ok(booking_view(booking))


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    authenticate(("Coordinator",))
    body = v.json_body()
    v.opt_string(body, "cancellation_reason")

    booking = lookup.get_booking(booking_id)
    if booking["status"] != "SCHEDULED":
        fail(errors.ERR_BOOKING_NOT_SCHEDULED,
             "Only a SCHEDULED stay may be cancelled.")

    booking["status"] = "CANCELLED"
    touch(booking)

    # Departing side: the work evaporates.
    for turnover in _outgoing_turnovers(booking["id"]):
        void_turnover(turnover)

    # Arriving side: the work survives and merely loses its deadline.
    for turnover in _incoming_turnovers(booking["id"]):
        turnover["incoming_booking_id"] = None
        prop = db.properties[turnover["property_id"]]
        outgoing, _ = turnover_boundaries(turnover)
        derived = preview_recompute(turnover, prop, outgoing, None, incoming_is_set=True)
        apply_window(turnover, derived)
        turnover["escalation_required"] = derived["slack_minutes"] < 0
        touch(turnover)

    return ok(booking_view(booking))


@bp.post("/bookings/<booking_id>/guest-review")
def guest_review(booking_id):
    authenticate(("Coordinator",))
    body = v.json_body()
    rating = v.req_int(body, "cleanliness_rating", minimum=1, maximum=5)

    booking = lookup.get_booking(booking_id)
    if now() < booking["checkin_at"]:
        fail(errors.ERR_INVALID_TIME_INTERVAL,
             "A cleanliness review is accepted only once the clock reaches checkin_at.")
    if booking["cleanliness_rating"] is not None:
        fail(errors.ERR_GUEST_REVIEW_ALREADY_SUBMITTED,
             "This stay already carries a cleanliness review.")

    booking["cleanliness_rating"] = rating
    booking["cleanliness_rated_at"] = now()
    touch(booking)
    return ok(booking_view(booking))

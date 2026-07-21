"""Admissions: reads, voiding and undo-check-in (PRD §3.5)."""
from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, serializers, workflow

bp = Blueprint("attendees", __name__)


def _guard_read(actor, attendee):
    lookup.require_buyer_is(actor, attendee["buyer_id"])
    event = db.store.events.get(attendee["event_id"])
    if event is not None:
        lookup.require_organizer_owns_event(actor, event)


@bp.route("/api/attendees/<attendee_id>", methods=["GET"])
def read_attendee(attendee_id):
    actor = middleware.authenticate(
        ["Buyer", "Organizer", "GateStaff", "FinanceOfficer", "PlatformAdmin"]
    )
    record = lookup.attendee(attendee_id)
    _guard_read(actor, record)
    return object_response(serializers.attendee(record))


@bp.route("/api/attendees", methods=["GET"])
def list_attendees():
    middleware.authenticate(
        ["Buyer", "Organizer", "GateStaff", "FinanceOfficer", "PlatformAdmin"]
    )
    order_id = request.args.get("order_id")
    order_item_id = request.args.get("order_item_id")
    ticket_type_id = request.args.get("ticket_type_id")
    event_id = request.args.get("event_id")
    buyer_id = request.args.get("buyer_id")
    seat_block_id = request.args.get("seat_block_id")
    status = middleware.query_enum("status", C.ATTENDEE_STATUSES)

    records = [
        a
        for a in db.store.attendees.values()
        if (order_id is None or a["order_id"] == order_id)
        and (order_item_id is None or a["order_item_id"] == order_item_id)
        and (ticket_type_id is None or a["ticket_type_id"] == ticket_type_id)
        and (event_id is None or a["event_id"] == event_id)
        and (buyer_id is None or a["buyer_id"] == buyer_id)
        and (seat_block_id is None or a["seat_block_id"] == seat_block_id)
        and (status is None or a["status"] == status)
    ]
    return paginate(db.ordered(records), serializers.attendee)


@bp.route("/api/attendees/<attendee_id>/void", methods=["POST"])
def void_attendee(attendee_id):
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    middleware.opt_string(payload, "reason")

    attendee = lookup.attendee(attendee_id)
    event = lookup.event(attendee["event_id"])
    lookup.require_organizer_owns_event(actor, event)

    if event["status"] == "COMPLETED":
        raise ApiError(
            "ERR_INVALID_EVENT_TRANSITION", "Admissions cannot be voided once the event is completed."
        )
    if attendee["status"] == "VOIDED":
        raise ApiError("ERR_TICKET_VOIDED", "The admission is already voided.")

    attendee["status"] = "VOIDED"
    attendee["checked_in_at"] = None
    db.touch(attendee)

    derive.recompute_event_issued(event)
    derive.recompute_event_checked_in(event)
    return object_response(serializers.attendee(attendee))


@bp.route("/api/attendees/<attendee_id>/undo-check-in", methods=["POST"])
def undo_check_in(attendee_id):
    actor = middleware.authenticate(["GateStaff", "Organizer"])
    middleware.body()

    attendee = lookup.attendee(attendee_id)
    event = lookup.event(attendee["event_id"])
    lookup.require_organizer_owns_event(actor, event)

    if attendee["status"] != "CHECKED_IN":
        raise ApiError("ERR_ATTENDEE_NOT_ISSUED", "The admission is not checked in.")

    attendee["status"] = "ISSUED"
    attendee["checked_in_at"] = None
    db.touch(attendee)

    derive.recompute_event_checked_in(event)
    order = db.store.orders.get(attendee["order_id"])
    if order is not None:
        workflow.rederive_order_fulfillment(order)
    return object_response(serializers.attendee(attendee))

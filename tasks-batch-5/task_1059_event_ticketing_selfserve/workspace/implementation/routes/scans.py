"""Gate scanning (PRD §3.5)."""
import datetime

from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, serializers, workflow

bp = Blueprint("scans", __name__)


@bp.route("/api/scans", methods=["POST"])
def create_scan():
    actor = middleware.authenticate(["GateStaff"])
    payload = middleware.body()
    attendee_id = middleware.req_string(payload, "attendee_id")
    event_id = middleware.req_string(payload, "event_id")
    gate_code = middleware.req_string(payload, "gate_code")

    event = lookup.event(event_id)
    attendee = lookup.attendee(attendee_id)

    # state — the gate is only open across the selling and closed statuses
    if event["status"] not in ("ONSALE", "PAUSED", "SALES_CLOSED"):
        raise ApiError("ERR_EVENT_NOT_ONSALE", "The event's gate is not open.")

    # temporal — the check-in window, inclusive on both bounds
    now = db.now()
    opens = db.parse_iso(event["starts_at"]) - datetime.timedelta(
        minutes=C.CHECK_IN_WINDOW_BEFORE_MINUTES
    )
    closes = db.parse_iso(event["ends_at"]) + datetime.timedelta(
        minutes=C.CHECK_IN_WINDOW_AFTER_MINUTES
    )
    if now < opens or now > closes:
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED", "The check-in window is closed.")

    # referential
    if attendee["event_id"] != event["id"]:
        raise ApiError(
            "ERR_ATTENDEE_EVENT_MISMATCH", "The admission belongs to a different event."
        )

    # safety
    if attendee["status"] == "VOIDED":
        raise ApiError("ERR_TICKET_VOIDED", "The admission has been voided.")
    if attendee["status"] == "CHECKED_IN":
        raise ApiError("ERR_ALREADY_CHECKED_IN", "The admission is already checked in.")
    if attendee["status"] not in ("ISSUED", "TRANSFERRED"):
        raise ApiError("ERR_ATTENDEE_NOT_ISSUED", "The admission is not scannable.")

    attendee["status"] = "CHECKED_IN"
    attendee["checked_in_at"] = db.now_iso()
    db.touch(attendee)

    record = db.base_record(with_version=False)
    record.update(
        {
            "attendee_id": attendee["id"],
            "event_id": event["id"],
            "gate_code": gate_code,
            "scanned_at": db.now_iso(),
            "scanned_by_user_id": actor.user_id,
        }
    )
    db.store.scans[record["id"]] = record

    derive.recompute_event_checked_in(event)
    order = db.store.orders.get(attendee["order_id"])
    if order is not None:
        workflow.rederive_order_fulfillment(order)

    return object_response(serializers.scan(record), 201)


@bp.route("/api/scans/<scan_id>", methods=["GET"])
def read_scan(scan_id):
    middleware.authenticate(["GateStaff", "Organizer", "PlatformAdmin"])
    record = lookup.scan(scan_id)
    return object_response(serializers.scan(record))


@bp.route("/api/scans", methods=["GET"])
def list_scans():
    middleware.authenticate(["GateStaff", "Organizer", "PlatformAdmin"])
    attendee_id = request.args.get("attendee_id")
    event_id = request.args.get("event_id")
    records = [
        s
        for s in db.store.scans.values()
        if (attendee_id is None or s["attendee_id"] == attendee_id)
        and (event_id is None or s["event_id"] == event_id)
    ]
    return paginate(db.ordered(records), serializers.scan)

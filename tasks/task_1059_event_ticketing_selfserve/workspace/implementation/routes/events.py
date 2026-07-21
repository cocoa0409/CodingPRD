"""Event lifecycle (PRD §3.2), cancellation cascade (§3.8) and reporting (§3.9)."""
import datetime
from decimal import Decimal

from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, serializers, workflow
from services.money import round_half_up

bp = Blueprint("events", __name__)


def _interval(starts_at, ends_at):
    return (
        starts_at,
        ends_at + datetime.timedelta(minutes=C.VENUE_TURNAROUND_MINUTES),
    )


@bp.route("/api/events", methods=["POST"])
def create_event():
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    organizer_id = middleware.req_string(payload, "organizer_id")
    venue_id = middleware.req_string(payload, "venue_id")
    title = middleware.req_string(payload, "title")
    starts_at = middleware.req_datetime(payload, "starts_at")
    ends_at = middleware.req_datetime(payload, "ends_at")
    fee_mode = middleware.opt_enum(payload, "fee_mode", C.FEE_MODES, "PASS_ON")
    refund_policy = middleware.opt_enum(
        payload, "refund_policy", C.REFUND_POLICIES, "FEE_RETAINED"
    )

    organizer = lookup.organizer(organizer_id)
    venue = lookup.venue(venue_id)

    if actor.role == "Organizer" and actor.user_id != organizer["id"]:
        lookup.unauthorized()

    now = db.now()
    if starts_at <= now or ends_at <= starts_at:
        raise ApiError(
            "ERR_EVENT_START_IN_PAST",
            "starts_at must be strictly in the future and ends_at strictly after starts_at.",
        )

    new_start, new_end = _interval(starts_at, ends_at)
    for other in db.store.events.values():
        if other["venue_id"] != venue["id"] or other["status"] == "CANCELLED":
            continue
        other_start, other_end = _interval(
            db.parse_iso(other["starts_at"]), db.parse_iso(other["ends_at"])
        )
        if new_start < other_end and other_start < new_end:
            raise ApiError(
                "ERR_VENUE_DOUBLE_BOOKED",
                "The venue is already booked over this interval.",
            )

    record = db.base_record()
    record.update(
        {
            "organizer_id": organizer["id"],
            "venue_id": venue["id"],
            "title": title,
            "starts_at": db.iso(starts_at),
            "ends_at": db.iso(ends_at),
            "status": "DRAFT",
            "fee_mode": fee_mode,
            "refund_policy": refund_policy,
            "gross_cents": 0,
            "refunds_cents": 0,
            "issued_count": 0,
            "checked_in_count": 0,
        }
    )
    db.store.events[record["id"]] = record
    return object_response(serializers.event(record), 201)


@bp.route("/api/events/<event_id>", methods=["GET"])
def read_event(event_id):
    middleware.authenticate(
        ["Organizer", "Buyer", "GateStaff", "FinanceOfficer", "PlatformAdmin", "Anonymous"]
    )
    record = lookup.event(event_id)
    return object_response(serializers.event(record))


@bp.route("/api/events", methods=["GET"])
def list_events():
    middleware.authenticate(
        ["Organizer", "Buyer", "GateStaff", "FinanceOfficer", "PlatformAdmin", "Anonymous"]
    )
    organizer_id = request.args.get("organizer_id")
    venue_id = request.args.get("venue_id")
    status = middleware.query_enum("status", C.EVENT_STATUSES)

    records = [
        e
        for e in db.store.events.values()
        if (organizer_id is None or e["organizer_id"] == organizer_id)
        and (venue_id is None or e["venue_id"] == venue_id)
        and (status is None or e["status"] == status)
    ]
    return paginate(db.ordered(records), serializers.event)


def _transition_target(event_id, allowed_roles=("Organizer",)):
    actor = middleware.authenticate(list(allowed_roles))
    middleware.body()
    record = lookup.event(event_id)
    lookup.require_organizer_owns_event(actor, record)
    return actor, record


def _invalid_transition():
    raise ApiError(
        "ERR_INVALID_EVENT_TRANSITION",
        "The requested transition is not declared from the event's current status.",
    )


@bp.route("/api/events/<event_id>/publish", methods=["POST"])
def publish_event(event_id):
    _, event = _transition_target(event_id)
    if event["status"] != "DRAFT":
        _invalid_transition()
    if not derive.ticket_types_of_event(event["id"]):
        _invalid_transition()
    if db.parse_iso(event["starts_at"]) <= db.now():
        raise ApiError("ERR_EVENT_START_IN_PAST", "starts_at is no longer in the future.")
    event["status"] = "ONSALE"
    db.touch(event)
    return object_response(serializers.event(event))


@bp.route("/api/events/<event_id>/pause", methods=["POST"])
def pause_event(event_id):
    _, event = _transition_target(event_id)
    if event["status"] != "ONSALE":
        _invalid_transition()
    event["status"] = "PAUSED"
    db.touch(event)
    return object_response(serializers.event(event))


@bp.route("/api/events/<event_id>/resume", methods=["POST"])
def resume_event(event_id):
    _, event = _transition_target(event_id)
    if event["status"] != "PAUSED":
        _invalid_transition()
    if db.parse_iso(event["starts_at"]) <= db.now():
        raise ApiError("ERR_EVENT_START_IN_PAST", "starts_at is no longer in the future.")
    event["status"] = "ONSALE"
    db.touch(event)
    return object_response(serializers.event(event))


@bp.route("/api/events/<event_id>/close-sales", methods=["POST"])
def close_sales(event_id):
    _, event = _transition_target(event_id)
    if event["status"] not in ("ONSALE", "PAUSED"):
        _invalid_transition()
    event["status"] = "SALES_CLOSED"
    db.touch(event)
    for order in derive.orders_of_event(event["id"]):
        if order["fulfillment_status"] == "HELD":
            order["fulfillment_status"] = "EXPIRED"
            db.touch(order)
    return object_response(serializers.event(event))


@bp.route("/api/events/<event_id>/complete", methods=["POST"])
def complete_event(event_id):
    _, event = _transition_target(event_id)
    if event["status"] != "SALES_CLOSED":
        _invalid_transition()
    if db.parse_iso(event["ends_at"]) > db.now():
        raise ApiError("ERR_EVENT_NOT_ENDED", "The event has not ended yet.")
    event["status"] = "COMPLETED"
    derive.recompute_event_all(event)
    db.touch(event)
    return object_response(serializers.event(event))


@bp.route("/api/events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    middleware.opt_string(payload, "reason")
    event = lookup.event(event_id)
    lookup.require_organizer_owns_event(actor, event)
    if event["status"] not in ("DRAFT", "ONSALE", "PAUSED", "SALES_CLOSED"):
        _invalid_transition()
    workflow.cancel_event(event)
    return object_response(serializers.event(event))


@bp.route("/api/events/<event_id>/report", methods=["GET"])
def event_report(event_id):
    actor = middleware.authenticate(["Organizer", "PlatformAdmin", "FinanceOfficer"])
    event = lookup.event(event_id)
    lookup.require_organizer_owns_event(actor, event)

    tickets_sold = derive.event_issued_count(event["id"])
    checked_in = derive.event_checked_in_count(event["id"])
    voided = sum(
        1
        for a in db.store.attendees.values()
        if a["event_id"] == event["id"] and a["status"] == "VOIDED"
    )
    tier_ids = {t["id"] for t in derive.ticket_types_of_event(event["id"])}
    waitlist_depth = sum(
        1
        for w in db.store.waitlist_entries.values()
        if w["ticket_type_id"] in tier_ids and w["status"] == "WAITING"
    )
    if tickets_sold == 0:
        rate = 0.0
    else:
        rate = float(
            round_half_up(Decimal(checked_in) / Decimal(tickets_sold), 4)
        )

    return object_response(
        {
            "event_id": event["id"],
            "tickets_sold_count": tickets_sold,
            "checked_in_count": checked_in,
            "voided_count": voided,
            "gross_cents": event["gross_cents"],
            "refunds_cents": event["refunds_cents"],
            "net_to_organizer_cents": event["gross_cents"] - event["refunds_cents"],
            "check_in_rate": rate,
            "waitlist_depth": waitlist_depth,
        }
    )

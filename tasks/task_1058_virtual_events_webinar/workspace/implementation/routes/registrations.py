"""Registrations: two independent state axes, pricing, money (PRD 3.3-3.5)."""

from flask import Blueprint, g

import calc
import cascades
import db
from auth import authorize, own_entity, own_event
from db import S
from errors import ApiError
from response import ok, ok_list
from validate import (
    body, get_event, get_registration, get_ticket_type, opt_bool, opt_int,
    opt_str, pagination, paginate, qs, req_int, req_str,
)

bp = Blueprint("registrations", __name__)

ATTENDANCE_TERMINAL = ("WITHDRAWN", "ATTENDED", "NO_SHOW")


def fk(b, field, getter):
    """Resolve a body foreign key when it is syntactically usable."""
    value = b.get(field)
    if isinstance(value, str) and value:
        return getter(value)
    return None


def _owner_guard(registration):
    """Organizer owns via the event; Attendee owns the registration row itself."""
    if g.role == "Attendee":
        own_entity(registration["id"])
    else:
        event = S.events.get(registration.get("event_id"))
        if event is not None:
            own_event(event)


@bp.route("/api/registrations", methods=["POST"])
def create_registration():
    authorize("Organizer")
    b = body()

    # 4. body foreign keys, in declared field order
    event = fk(b, "event_id", get_event)
    ticket_type = fk(b, "ticket_type_id", get_ticket_type)

    # 5. ownership
    if event is not None:
        own_event(event)

    # 6. body shape
    req_str(b, "event_id")
    req_str(b, "ticket_type_id")
    attendee_email = req_str(b, "attendee_email")
    group_code = opt_str(b, "group_code")
    group_size = opt_int(b, "group_size", default=1, minimum=1)
    waitlist_if_full = opt_bool(b, "waitlist_if_full", default=False)

    # 8. duplicate-registration detection
    for r in S.registrations.values():
        if (
            r.get("event_id") == event["id"]
            and r.get("attendee_email") == attendee_email
            and r.get("attendance_status") != "WITHDRAWN"
        ):
            raise ApiError("ERR_DUPLICATE_REGISTRATION")

    # 11. the registration window gate
    if event.get("state") != "PUBLISHED":
        raise ApiError("ERR_EVENT_NOT_OPEN")

    # 16. fiscal rules
    sold_out = int(ticket_type.get("sold_count", 0)) >= int(ticket_type.get("quota", 0))
    at_capacity = int(event.get("registered_count", 0)) >= int(event.get("capacity", 0))

    waitlisted = False
    if sold_out or at_capacity:
        if waitlist_if_full is True:
            waitlisted = True
        elif sold_out:
            raise ApiError("ERR_TICKET_SOLD_OUT")
        else:
            raise ApiError("ERR_EVENT_CAPACITY_EXCEEDED")

    row = db.new_row({
        "event_id": event["id"],
        "ticket_type_id": ticket_type["id"],
        "attendee_email": attendee_email,
        "group_code": group_code,
        "group_size": group_size,
        "payment_status": "UNPAID",
        "attendance_status": "WAITLISTED" if waitlisted else "REGISTERED",
        "amount_due_cents": 0,
        "amount_paid_cents": 0,
        "final_amount_due_cents": None,
        "watched_minutes": 0,
        "accepted_meeting_count": 0,
    })
    S.registrations[row["id"]] = row

    if not waitlisted:
        row["amount_due_cents"] = calc.price_provisional(row, ticket_type, event)
        cascades.take_seat(row)

    db.touch(event)
    return ok(db.serialize(row), 201)


@bp.route("/api/registrations", methods=["GET"])
def list_registrations():
    authorize("Organizer", "PlatformAdmin", "FinanceAdmin")
    limit, offset = pagination()
    event_id = qs("event_id")
    ticket_type_id = qs("ticket_type_id")
    group_code = qs("group_code")
    payment_status = qs("payment_status")
    attendance_status = qs("attendance_status")
    rows = [
        r for r in S.registrations.values()
        if (event_id is None or r.get("event_id") == event_id)
        and (ticket_type_id is None or r.get("ticket_type_id") == ticket_type_id)
        and (group_code is None or r.get("group_code") == group_code)
        and (payment_status is None or r.get("payment_status") == payment_status)
        and (attendance_status is None or r.get("attendance_status") == attendance_status)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/registrations/<registration_id>", methods=["GET"])
def read_registration(registration_id):
    authorize("Organizer", "PlatformAdmin", "FinanceAdmin", "Attendee")
    row = get_registration(registration_id)
    return ok(db.serialize(row))


@bp.route("/api/registrations/<registration_id>/pay", methods=["POST"])
def pay_registration(registration_id):
    authorize("Organizer")
    reg = get_registration(registration_id)
    _owner_guard(reg)
    b = body()
    amount_cents = req_int(b, "amount_cents")

    if reg.get("payment_status") != "UNPAID":
        raise ApiError("ERR_INVALID_STATE")
    if reg.get("attendance_status") in ("WITHDRAWN", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE")
    if amount_cents != int(reg.get("amount_due_cents", 0)):
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    reg["payment_status"] = "PAID"
    reg["amount_paid_cents"] = amount_cents
    event = S.events.get(reg.get("event_id"))
    if event is not None:
        event["gross_collected_cents"] = int(event.get("gross_collected_cents", 0)) + amount_cents
        db.touch(event)
    db.touch(reg)
    return ok(db.serialize(reg))


@bp.route("/api/registrations/<registration_id>/refund", methods=["POST"])
def refund_registration(registration_id):
    authorize("Organizer")
    reg = get_registration(registration_id)
    _owner_guard(reg)
    b = body()
    req_str(b, "reason")

    if reg.get("payment_status") != "PAID":
        raise ApiError("ERR_INVALID_STATE")

    event = S.events.get(reg.get("event_id"))
    reg["payment_status"] = "REFUNDED"

    # link 1 - money and the seat, together
    refunded = int(reg.get("amount_paid_cents", 0))
    if event is not None:
        event["gross_collected_cents"] = int(event.get("gross_collected_cents", 0)) - refunded
    reg["amount_paid_cents"] = 0

    prior_attendance = reg.get("attendance_status")
    reg["attendance_status"] = "WITHDRAWN"
    ticket_type = None
    if prior_attendance not in ("WAITLISTED", "WITHDRAWN"):
        # link 2 - availability recomputation follows the seat release
        ticket_type = cascades.release_seat(reg)
    db.touch(reg)

    # link 3 - waitlist promotion follows the availability flip
    if ticket_type is not None and event is not None:
        cascades.promote_waitlist(ticket_type, event)

    if event is not None:
        db.touch(event)
    return ok(db.serialize(reg))


@bp.route("/api/registrations/<registration_id>/check-in", methods=["POST"])
def check_in_registration(registration_id):
    authorize("Organizer")
    reg = get_registration(registration_id)
    _owner_guard(reg)

    status = reg.get("attendance_status")
    if status != "REGISTERED":
        if status in ATTENDANCE_TERMINAL:
            raise ApiError("ERR_ALREADY_TERMINAL")
        raise ApiError("ERR_INVALID_STATE")

    event = S.events.get(reg.get("event_id"))
    if event is None or event.get("state") != "LIVE":
        raise ApiError("ERR_INVALID_STATE")

    reg["attendance_status"] = "CHECKED_IN"
    db.touch(reg)
    return ok(db.serialize(reg))


@bp.route("/api/registrations/<registration_id>/withdraw", methods=["POST"])
def withdraw_registration(registration_id):
    authorize("Organizer", "Attendee")
    reg = get_registration(registration_id)
    _owner_guard(reg)

    status = reg.get("attendance_status")
    if status not in ("WAITLISTED", "REGISTERED", "CHECKED_IN"):
        if status in ATTENDANCE_TERMINAL:
            raise ApiError("ERR_ALREADY_TERMINAL")
        raise ApiError("ERR_INVALID_STATE")

    reg["attendance_status"] = "WITHDRAWN"
    if status != "WAITLISTED":
        cascades.release_seat(reg)
    cascades.cancel_pending_match_requests(reg)
    db.touch(reg)

    event = S.events.get(reg.get("event_id"))
    if event is not None:
        db.touch(event)
    return ok(db.serialize(reg))

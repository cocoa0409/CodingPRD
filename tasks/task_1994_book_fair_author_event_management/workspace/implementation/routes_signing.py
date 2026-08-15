"""Signing sessions and signing tickets (line entitlements)."""

import uuid

from flask import Blueprint

import db
from db import fmt_dt, now_iso
from errors import fail
from middleware import ALL_ROLES, require_roles
from response import success, success_list
from routes_core import get_or_404
from services import (
    BOOKING_TERMINAL,
    cancel_session,
    compute_session_bonus,
    count_tickets,
    new_entity,
    signing_floor_exceeded,
    touch,
)
from util import (
    get_body,
    list_filtered,
    page,
    pagination_params,
    parse_dt_loose,
    v_datetime,
    v_enum,
    v_int,
    v_str,
    validate_body,
)

bp = Blueprint("signing", __name__)


# ---------------------------------------------------------------------------
# Signing sessions
# ---------------------------------------------------------------------------

@bp.post("/signing-sessions")
@require_roles("Organizer")
def create_session():
    data = get_body()
    booking_id = data.get("booking_id")
    if isinstance(booking_id, str) and booking_id not in db.bookings:
        fail("ERR_NOT_FOUND", "booking_id references no existing AuthorBooking")
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    vals = validate_body(
        data,
        [
            ("booking_id", True, v_str),
            ("fair_id", True, v_str),
            ("mode", True, v_enum("TICKETED", "FREE")),
            ("start_at", True, v_datetime),
            ("end_at", True, v_datetime),
            ("line_space_units", True, v_int(1)),
            ("capacity_seats", True, v_int(1)),
            ("admit_concurrent_cap", True, v_int(1)),
        ],
    )
    if not vals["end_at"] > vals["start_at"]:
        fail("ERR_VALIDATION", "end_at must be strictly after start_at")
    if vals["admit_concurrent_cap"] > vals["capacity_seats"]:
        fail("ERR_VALIDATION", "admit_concurrent_cap must be <= capacity_seats")
    fair = db.fairs[vals["fair_id"]]
    # Signing-floor capacity (closed-interval overlap) is checked at 12,
    # before the referential booking-fair match at 20.
    if signing_floor_exceeded(fair, vals["start_at"], vals["end_at"], vals["line_space_units"]):
        fail(
            "ERR_SIGNING_FLOOR_CAPACITY_EXCEEDED",
            "Overlapping sessions would exceed the fair's signing-floor capacity",
        )
    booking = db.bookings[vals["booking_id"]]
    if booking["fair_id"] != vals["fair_id"]:
        fail("ERR_LINE_FAIR_MISMATCH", "Booking belongs to a different fair")
    session = new_entity(
        booking_id=vals["booking_id"],
        fair_id=vals["fair_id"],
        mode=vals["mode"],
        start_at=fmt_dt(vals["start_at"]),
        end_at=fmt_dt(vals["end_at"]),
        line_space_units=vals["line_space_units"],
        capacity_seats=vals["capacity_seats"],
        admit_concurrent_cap=vals["admit_concurrent_cap"],
        attendance_count=None,
        bonus_cents=None,
        status="SCHEDULED",
    )
    db.sessions[session["id"]] = session
    return success(session, 201)


@bp.get("/signing-sessions")
@require_roles(*ALL_ROLES)
def list_sessions():
    limit, offset = pagination_params()
    items = list_filtered(
        db.sessions,
        [
            ("fair_id", "fair_id"),
            ("booking_id", "booking_id"),
            ("status", "status"),
            ("mode", "mode"),
        ],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/signing-sessions/<sid>")
@require_roles(*ALL_ROLES)
def get_session(sid):
    return success(get_or_404(db.sessions, sid, "SigningSession"))


@bp.post("/signing-sessions/<sid>/open-signing")
@require_roles("LineStaff")
def open_signing(sid):
    session = get_or_404(db.sessions, sid, "SigningSession")
    validate_body(get_body(), [])
    if session["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Session is not in SCHEDULED")
    booking = db.bookings[session["booking_id"]]
    if booking["status"] != "TRAVEL_BOOKED":
        fail("ERR_BOOKING_NOT_TRAVEL_READY", "Session's booking must be TRAVEL_BOOKED")
    fair = db.fairs[session["fair_id"]]
    if fair["status"] != "OPEN":
        fail("ERR_FAIR_NOT_OPEN", "Session's fair must be OPEN")
    start = parse_dt_loose(session["start_at"])
    end = parse_dt_loose(session["end_at"])
    if not (start <= db.logical_clock <= end):
        fail("ERR_OUTSIDE_SIGNING_WINDOW", "Logical clock is outside the signing window")
    session["status"] = "OPEN_FOR_SIGNING"
    touch(session)
    return success(session)


@bp.post("/signing-sessions/<sid>/close-signing")
@require_roles("LineStaff")
def close_signing(sid):
    session = get_or_404(db.sessions, sid, "SigningSession")
    validate_body(get_body(), [])
    if session["status"] != "OPEN_FOR_SIGNING":
        fail("ERR_INVALID_STATE", "Session is not in OPEN_FOR_SIGNING")
    admitted = 0
    redeemed = 0
    for ticket in db.tickets.values():
        if ticket["session_id"] != session["id"]:
            continue
        if ticket["status"] == "ISSUED":
            ticket["status"] = "NO_SHOW"
        elif ticket["status"] == "ADMITTED":
            admitted += 1
        elif ticket["status"] == "REDEEMED":
            redeemed += 1
    session["attendance_count"] = admitted + redeemed
    session["status"] = "CLOSED_FOR_SIGNING"
    touch(session)
    return success(session)


@bp.post("/signing-sessions/<sid>/reconcile")
@require_roles("Organizer")
def reconcile_session(sid):
    session = get_or_404(db.sessions, sid, "SigningSession")
    validate_body(get_body(), [])
    if session["status"] != "CLOSED_FOR_SIGNING":
        fail("ERR_INVALID_STATE", "Session is not in CLOSED_FOR_SIGNING")
    booking = db.bookings[session["booking_id"]]
    if booking["status"] in BOOKING_TERMINAL:
        fail("ERR_INVALID_STATE", "Session's booking is in a terminal state")
    bonus = compute_session_bonus(session, booking)
    session["bonus_cents"] = bonus
    session["status"] = "RECONCILED"
    touch(session)
    booking["accrued_bonus_cents"] += bonus
    touch(booking)
    return success(session)


@bp.post("/signing-sessions/<sid>/cancel")
@require_roles("Organizer")
def cancel_session_endpoint(sid):
    session = get_or_404(db.sessions, sid, "SigningSession")
    validate_body(get_body(), [])
    if session["status"] not in ("SCHEDULED", "OPEN_FOR_SIGNING", "CLOSED_FOR_SIGNING"):
        fail("ERR_INVALID_STATE", "Session cannot be cancelled from its current state")
    cancel_session(session)
    return success(session)


# ---------------------------------------------------------------------------
# Signing tickets (no updated_at / version per PRD section 2.4)
# ---------------------------------------------------------------------------

@bp.post("/signing-tickets")
@require_roles("LineStaff")
def create_ticket():
    data = get_body()
    session_id = data.get("session_id")
    if isinstance(session_id, str) and session_id not in db.sessions:
        fail("ERR_NOT_FOUND", "session_id references no existing SigningSession")
    vals = validate_body(data, [("session_id", True, v_str), ("holder_name", True, v_str)])
    session = db.sessions[vals["session_id"]]
    live = count_tickets(session["id"], ("ISSUED", "ADMITTED", "REDEEMED"))
    if live >= session["capacity_seats"]:
        fail("ERR_SIGNING_CAPACITY_EXCEEDED", "Session live-entitlement capacity reached")
    ticket = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "session_id": session["id"],
        "kind": "TICKET" if session["mode"] == "TICKETED" else "WRISTBAND",
        "holder_name": vals["holder_name"],
        "status": "ISSUED",
    }
    db.tickets[ticket["id"]] = ticket
    return success(ticket, 201)


@bp.get("/signing-tickets")
@require_roles(*ALL_ROLES)
def list_tickets():
    limit, offset = pagination_params()
    items = list_filtered(
        db.tickets,
        [("session_id", "session_id"), ("status", "status"), ("kind", "kind")],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/signing-tickets/<tid>")
@require_roles(*ALL_ROLES)
def get_ticket(tid):
    return success(get_or_404(db.tickets, tid, "SigningTicket"))


@bp.post("/signing-tickets/<tid>/admit")
@require_roles("LineStaff")
def admit_ticket(tid):
    ticket = get_or_404(db.tickets, tid, "SigningTicket")
    data = get_body()
    payload_session_id = data.get("session_id")
    if isinstance(payload_session_id, str) and payload_session_id not in db.sessions:
        fail("ERR_NOT_FOUND", "session_id references no existing SigningSession")
    vals = validate_body(data, [("session_id", True, v_str)])
    payload_session = db.sessions[vals["session_id"]]
    # Pinned order: state (8) -> safety (10) -> referential (20). All
    # session-scoped checks run against the PAYLOAD session.
    if ticket["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Ticket is not in ISSUED")
    if payload_session["status"] != "OPEN_FOR_SIGNING":
        fail("ERR_SESSION_NOT_SIGNING", "Payload session is not OPEN_FOR_SIGNING")
    admitted = count_tickets(payload_session["id"], ("ADMITTED",))
    if admitted >= payload_session["admit_concurrent_cap"]:
        fail("ERR_LINE_CAPACITY_EXCEEDED", "Session admit_concurrent_cap reached")
    if vals["session_id"] != ticket["session_id"]:
        fail("ERR_TICKET_SESSION_MISMATCH", "Payload session_id differs from the ticket's session")
    ticket["status"] = "ADMITTED"
    return success(ticket)


@bp.post("/signing-tickets/<tid>/redeem")
@require_roles("LineStaff")
def redeem_ticket(tid):
    ticket = get_or_404(db.tickets, tid, "SigningTicket")
    validate_body(get_body(), [])
    if ticket["status"] != "ADMITTED":
        fail("ERR_INVALID_STATE", "Ticket is not in ADMITTED")
    session = db.sessions[ticket["session_id"]]
    if session["status"] not in ("OPEN_FOR_SIGNING", "CLOSED_FOR_SIGNING"):
        fail("ERR_SESSION_NOT_SIGNING", "Session is not OPEN_FOR_SIGNING or CLOSED_FOR_SIGNING")
    ticket["status"] = "REDEEMED"
    return success(ticket)


@bp.post("/signing-tickets/<tid>/void")
@require_roles("LineStaff")
def void_ticket(tid):
    ticket = get_or_404(db.tickets, tid, "SigningTicket")
    validate_body(get_body(), [])
    if ticket["status"] not in ("ISSUED", "ADMITTED"):
        fail("ERR_INVALID_STATE", "Ticket cannot be voided from its current state")
    ticket["status"] = "VOIDED"
    return success(ticket)

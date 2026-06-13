"""Booking lifecycle routes: create, fetch, list, confirm, cancel,
check-in, check-out (PRD §3.2 - §3.4, §3.7)."""
from flask import Blueprint, request

from db import db, clock_now
from errors import err
from middleware import get_principal, require_roles
from helpers import (
    get_json_body, require_str, require_enum, get_pagination, paginate,
    get_or_404, stamp_common, touch,
)
from response import success_object, success_array
from serialize import public, public_list
from timeutil import parse_iso, add_hours, add_minutes
from services import calc
from services import booking_logic as bl

bp = Blueprint("bookings", __name__)


def _owns_booking(principal, booking):
    """Client ownership: client_id must equal X-User-ID (PRD §2.1)."""
    if principal.role == "Client" and booking["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only act on their own bookings")


# ---------------------------------------------------------------------------
# Create (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.route("/studio/bookings", methods=["POST"])
def create_booking():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    room_id = require_str(body, "room_id")
    client_id = require_str(body, "client_id")
    booking_kind = require_enum(body, "booking_kind", {"HOURLY", "BLOCK", "LOCKOUT"})
    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")

    # Existence (left-to-right path then body FKs). No path ids here; body FKs.
    studio = get_or_404(db.studios, studio_id, "studio")
    room = get_or_404(db.rooms, room_id, "room")
    client = get_or_404(db.clients, client_id, "client")

    # Client ownership: a client may only create bookings for their own id.
    if principal.role == "Client" and client_id != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only create bookings under their own id")

    start_at = parse_iso(start_raw)
    end_at = parse_iso(end_raw)

    # Temporal validity (PRD §3.2): end strictly after start.
    if not (end_at > start_at):
        raise err("ERR_INVALID_TIME_RANGE", "end_at must be strictly after start_at")

    base_charge = calc.base_charge_cents(booking_kind, start_at, end_at, room)
    deposit_due = calc.deposit_due_cents(base_charge, studio["deposit_pct"])
    hold_expires = add_hours(clock_now(), 24)

    booking = {
        "studio_id": studio_id,
        "room_id": room_id,
        "client_id": client_id,
        "parent_series_id": None,
        "booking_kind": booking_kind,
        "is_series_anchor": False,
        "start_at": _iso(start_at),
        "end_at": _iso(end_at),
        "actual_end_at": None,
        "schedule_status": "HELD",
        "settlement_status": "AWAITING_DEPOSIT",
        "base_charge_cents": base_charge,
        "deposit_due_cents": deposit_due,
        "overtime_cents": 0,
        "total_charge_cents": 0,
        "amount_paid_cents": 0,
        "hold_expires_at": _iso(hold_expires),
    }
    stamp_common(booking)
    db.bookings[booking["id"]] = booking
    return success_object(public(booking), status=201)


def _iso(dt):
    from db import db_iso
    return db_iso(dt)


# ---------------------------------------------------------------------------
# Fetch / List
# ---------------------------------------------------------------------------

@bp.route("/studio/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    booking = get_or_404(db.bookings, bid, "booking")
    if principal.role == "Client":
        _owns_booking(principal, booking)
    elif principal.role == "Engineer":
        # Engineer may read a booking they are assigned to.
        assigned = any(
            a["engineer_id"] == principal.user_id and a["booking_id"] == bid
            for a in db.engineer_assignments.values()
        )
        if not assigned:
            raise err("ERR_FORBIDDEN", "engineer not assigned to this booking")
    return success_object(public(booking))


@bp.route("/studio/bookings", methods=["GET"])
def list_bookings():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    bookings = list(db.bookings.values())
    for key in ("studio_id", "room_id", "client_id", "parent_series_id", "schedule_status"):
        val = request.args.get(key)
        if val is not None:
            bookings = [b for b in bookings if b.get(key) == val]
    # Scope by role visibility.
    if principal.role == "Client":
        bookings = [b for b in bookings if b["client_id"] == principal.user_id]
    elif principal.role == "Engineer":
        assigned_booking_ids = {
            a["booking_id"] for a in db.engineer_assignments.values()
            if a["engineer_id"] == principal.user_id
        }
        bookings = [b for b in bookings if b["id"] in assigned_booking_ids]
    limit, offset = get_pagination()
    page, total = paginate(bookings, limit, offset)
    return success_array(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Confirm (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.route("/studio/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    booking = get_or_404(db.bookings, bid, "booking")

    # State check: must be HELD.
    if booking["schedule_status"] != "HELD":
        raise err("ERR_INVALID_STATE", "booking is not HELD")
    # Deposit must be paid.
    if booking["settlement_status"] != "DEPOSIT_PAID":
        raise err("ERR_INVALID_STATE", "deposit has not been paid")

    room = db.rooms[booking["room_id"]]
    # Room bookable: status OPEN, or this booking is an occurrence of the
    # lockout contract that LOCKED the room (parent_series_id set).
    room_ok = room["status"] == "OPEN" or booking.get("parent_series_id") is not None
    if not room_ok:
        raise err("ERR_INVALID_STATE", "room is not bookable")

    # Room overlap check (PRD §2.9 / §3.2): buffered footprint vs other
    # CONFIRMED/IN_SESSION bookings on the same room.
    my_start, my_end_buf = bl.room_footprint(booking, room)
    for other in db.bookings.values():
        if other["id"] == bid:
            continue
        if other["room_id"] != booking["room_id"]:
            continue
        if other["schedule_status"] not in ("CONFIRMED", "IN_SESSION"):
            continue
        o_start, o_end_buf = bl.room_footprint(other, room)
        if bl.intervals_overlap(my_start, my_end_buf, o_start, o_end_buf):
            raise err("ERR_ROOM_UNAVAILABLE", "room window collides with another booking")

    booking["schedule_status"] = "CONFIRMED"
    booking["hold_expires_at"] = None
    touch(booking)
    return success_object(public(booking))


# ---------------------------------------------------------------------------
# Cancel (PRD §3.7)
# ---------------------------------------------------------------------------

@bp.route("/studio/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    booking = get_or_404(db.bookings, bid, "booking")
    if principal.role == "Client":
        _owns_booking(principal, booking)

    sched = booking["schedule_status"]
    if sched not in ("HELD", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "booking cannot be cancelled from %s" % sched)

    # CONFIRMED extra guard: clock must be before start_at.
    if sched == "CONFIRMED":
        start_at = parse_iso(booking["start_at"])
        if clock_now() >= start_at:
            raise err("ERR_CANCEL_TOO_LATE", "cannot cancel a session that has started")

    studio = db.studios[booking["studio_id"]]
    bl.perform_cancellation(booking, studio, booking["client_id"])
    return success_object(public(booking))


# ---------------------------------------------------------------------------
# Check-in (PRD §3.3)
# ---------------------------------------------------------------------------

@bp.route("/studio/bookings/<bid>/check-in", methods=["POST"])
def check_in_booking(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    booking = get_or_404(db.bookings, bid, "booking")

    if booking["schedule_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "booking is not CONFIRMED")

    start_at = parse_iso(booking["start_at"])
    if clock_now() < start_at:
        raise err("ERR_INVALID_STATE", "the scheduled start has not been reached")

    # Safety: every RESERVED requires_engineer gear rental must have >=1
    # ASSIGNED engineer assignment (PRD §3.3).
    assignments = [a for a in bl.engineer_assignments_of(bid) if a["status"] == "ASSIGNED"]
    has_engineer = len(assignments) >= 1
    for rental in bl.gear_rentals_of(bid):
        if rental["status"] != "RESERVED":
            continue
        gear = db.gear_items.get(rental["gear_item_id"])
        if gear is not None and gear["requires_engineer"] and not has_engineer:
            raise err("ERR_ENGINEER_REQUIRED", "engineer-required gear has no engineer assigned")

    booking["schedule_status"] = "IN_SESSION"
    touch(booking)
    return success_object(public(booking))


# ---------------------------------------------------------------------------
# Check-out (PRD §3.3, §3.4, §3.5)
# ---------------------------------------------------------------------------

@bp.route("/studio/bookings/<bid>/check-out", methods=["POST"])
def check_out_booking(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    booking = get_or_404(db.bookings, bid, "booking")
    body = get_json_body()
    actual_end_raw = require_str(body, "actual_end_at")

    if booking["schedule_status"] != "IN_SESSION":
        raise err("ERR_INVALID_STATE", "booking is not IN_SESSION")

    actual_end = parse_iso(actual_end_raw, error_id="ERR_INVALID_REQUEST")
    start_at = parse_iso(booking["start_at"])
    if actual_end < start_at:
        raise err("ERR_INVALID_TIME_RANGE", "actual_end_at must be at or after start_at")

    end_at = parse_iso(booking["end_at"])
    studio = db.studios[booking["studio_id"]]
    room = db.rooms[booking["room_id"]]

    # --- Overtime (PRD §3.4) ---
    overage_minutes = calc.billable_overage_minutes(
        actual_end, end_at, studio["overtime_grace_minutes"]
    )
    room_surcharge = calc.room_overtime_surcharge_cents(
        overage_minutes, room["hourly_rate_cents"], studio["overtime_multiplier"]
    )

    # Engineer overtime surcharge across non-released (ASSIGNED) assignments.
    assignments = [a for a in bl.engineer_assignments_of(bid) if a["status"] == "ASSIGNED"]
    engineer_surcharge = 0
    for a in assignments:
        eng = db.engineers[a["engineer_id"]]
        engineer_surcharge += calc.engineer_overtime_surcharge_cents(
            overage_minutes, eng["hourly_rate_cents"]
        )

    overtime_cents = room_surcharge + engineer_surcharge

    overtime_record = {
        "booking_id": bid,
        "overage_minutes": overage_minutes,
        "room_surcharge_cents": room_surcharge,
        "engineer_surcharge_cents": engineer_surcharge,
    }
    # Lean entity: only id + created_at (PRD §2.4).
    from db import new_id, now_iso_millis
    overtime_record["id"] = new_id()
    overtime_record["created_at"] = now_iso_millis()
    overtime_record["_seq"] = db.next_seq()
    db.overtime_records[overtime_record["id"]] = overtime_record

    booking["overtime_cents"] = overtime_cents
    booking["actual_end_at"] = _iso(actual_end)

    # --- Finalize engineer assignments (PRD §3.5) ---
    overtime_qh = calc.overtime_hours_quarter(overage_minutes)
    for a in assignments:
        eng = db.engineers[a["engineer_id"]]
        billed_hours, charge = calc.engineering_final_cents(
            a["scheduled_hours"], overtime_qh, eng["hourly_rate_cents"]
        )
        a["billed_hours"] = billed_hours
        a["charge_cents"] = charge
        touch(a)

    # --- Reconcile total (PRD §3.3) ---
    bl.reconcile_total(booking)

    # --- Settlement axis: DEPOSIT_PAID -> BALANCE_DUE ---
    booking["settlement_status"] = "BALANCE_DUE"
    booking["schedule_status"] = "COMPLETED"
    touch(booking)
    return success_object(public(booking))


# ---------------------------------------------------------------------------
# Overtime records (read)
# ---------------------------------------------------------------------------

@bp.route("/studio/bookings/<bid>/overtime-records", methods=["GET"])
def list_overtime_records(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    booking = get_or_404(db.bookings, bid, "booking")
    if principal.role == "Client":
        _owns_booking(principal, booking)
    records = [r for r in db.overtime_records.values() if r["booking_id"] == bid]
    limit, offset = get_pagination()
    page, total = paginate(records, limit, offset)
    return success_array(public_list(page), limit, offset, total)

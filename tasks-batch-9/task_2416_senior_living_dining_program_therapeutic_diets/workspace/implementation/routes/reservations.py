"""The reservation book: spacing, capacity, waitlists and seating."""
from datetime import timedelta

from flask import Blueprint

import serialize
from auth import authenticate, require_own_indirect, rep_scope
from clock import clock, fmt_instant
from constants import MEAL_PERIODS, RESERVATION_STATUSES
from db import base_row, db, sort_created, touch
from errors import ApiError, api_error
from response import created, ok, ok_list
from routes.common import DSM, EVERY_ROLE, get_reservation, get_resident, get_venue
from services import calc, derive
from shape import (
    body_json, opt_bool, opt_str, paginate, parse_date_str, q_date, q_enum,
    q_str, req_date, req_enum, req_instant, req_int, req_str,
)

bp = Blueprint("reservations", __name__)


@bp.get("/seating-reservations/<reservation_id>")
def read_reservation(reservation_id):
    ctx = authenticate(EVERY_ROLE)
    row = get_reservation(reservation_id)
    require_own_indirect(ctx, row)
    return ok(serialize.reservation(row))


@bp.get("/seating-reservations")
def list_reservations():
    ctx = authenticate(EVERY_ROLE)
    venue_id = q_str("venue_id")
    resident_id = q_str("resident_id")
    service_date = q_date("service_date")
    meal_period = q_enum("meal_period", MEAL_PERIODS)
    status = q_enum("status", RESERVATION_STATUSES)

    scope = rep_scope(ctx)
    if scope is not None and resident_id is not None and resident_id != scope:
        raise api_error(
            "ERR_FORBIDDEN_ROLE",
            "A ResidentRepresentative may only list its own resident's reservations",
        )

    rows = list(db.reservations.values())
    if scope is not None:
        rows = [r for r in rows if r["resident_id"] == scope]
    if venue_id is not None:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if resident_id is not None:
        rows = [r for r in rows if r["resident_id"] == resident_id]
    if service_date is not None:
        rows = [r for r in rows if r["service_date"] == service_date[0]]
    if meal_period is not None:
        rows = [r for r in rows if r["meal_period"] == meal_period]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.reservation, window), pagination)


@bp.post("/seating-reservations")
def create_reservation():
    authenticate([DSM])
    body = body_json()
    resident_id = req_str(body, "resident_id")
    venue_id = req_str(body, "venue_id")
    service_date_str, service_date = req_date(body, "service_date")
    meal_period = req_enum(body, "meal_period", MEAL_PERIODS)
    seat_start = req_instant(body, "seat_start_utc")
    party_size = req_int(body, "party_size", minimum=1)
    expected_venue_version = req_int(body, "expected_venue_version")
    allow_waitlist = opt_bool(body, "allow_waitlist", default=False)

    if seat_start.date() != service_date:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "service_date must equal the UTC calendar date of seat_start_utc",
        )

    resident = get_resident(resident_id)
    venue = get_venue(venue_id)

    if resident["community_id"] != venue["community_id"]:
        raise api_error(
            "ERR_CROSS_COMMUNITY_REFERENCE",
            "The resident and the venue must belong to the same community",
        )

    if expected_venue_version != venue["version"]:
        raise api_error(
            "ERR_STALE_VERSION",
            "expected_venue_version %s does not match the venue's current version %s"
            % (expected_venue_version, venue["version"]),
        )

    if venue["status"] != "OPEN" or venue["temp_compliance_posture"] == "SUSPENDED":
        raise api_error(
            "ERR_VENUE_SERVICE_SUSPENDED",
            "The venue is not currently able to serve",
        )

    if derive.find_verified_order(resident_id) is None:
        raise api_error(
            "ERR_DIET_ORDER_NOT_VERIFIED",
            "The resident needs a clinical_status ACTIVE, review_status APPROVED diet order",
        )

    if resident["dining_status"] != "ACTIVE":
        raise api_error(
            "ERR_RESIDENT_NOT_ACTIVE",
            "Only an ACTIVE resident may be booked into a seating window",
        )

    if resident["care_level"] not in venue["care_levels_served"]:
        raise api_error(
            "ERR_CARE_LEVEL_NOT_SERVED",
            "The venue does not serve the resident's care level",
        )

    seat_end = seat_start + timedelta(minutes=venue["seating_turn_minutes"])

    if calc.resident_meal_spacing_conflict(resident_id, seat_start, seat_end):
        raise api_error(
            "ERR_RESIDENT_MEAL_SPACING",
            "The candidate seating crowds another seating of this resident",
        )

    committed = calc.venue_capacity_committed(venue, service_date_str, seat_start, seat_end)
    status = "RESERVED"
    if committed + party_size > venue["seat_capacity"]:
        if not allow_waitlist:
            raise api_error(
                "ERR_VENUE_CAPACITY_EXCEEDED",
                "The venue has no capacity left for the requested seating window",
            )
        status = "WAITLISTED"

    row = base_row()
    row.update({
        "resident_id": resident_id,
        "venue_id": venue_id,
        "service_date": service_date_str,
        "meal_period": meal_period,
        "seat_start_utc": fmt_instant(seat_start),
        "seat_end_utc": fmt_instant(seat_end),
        "party_size": party_size,
        "allow_waitlist": allow_waitlist,
        "status": status,
        "suspension_hold": False,
        "seated_at": None,
    })
    db.reservations[row["id"]] = row
    touch(venue)
    return created(serialize.reservation(row))


@bp.post("/seating-reservations/<reservation_id>/seat")
def seat_reservation(reservation_id):
    ctx = authenticate([DSM])
    body_json()

    row = get_reservation(reservation_id)
    if row["status"] != "RESERVED":
        raise api_error("ERR_INVALID_STATE", "Only a RESERVED reservation may be seated")

    venue = db.venues.get(row["venue_id"])
    if venue is None or venue["status"] != "OPEN" or venue["temp_compliance_posture"] == "SUSPENDED":
        raise api_error(
            "ERR_VENUE_SERVICE_SUSPENDED",
            "The venue is not currently able to serve",
        )

    resident = db.residents.get(row["resident_id"])
    service_date = parse_date_str("service_date", row["service_date"])

    missing_cycle = False
    card = None
    try:
        card = derive.tray_card_resolution(
            resident, row["service_date"], service_date, row["meal_period"]
        )
    except ApiError as exc:
        if exc.error_id != "ERR_NO_PUBLISHED_MENU_CYCLE":
            raise
        missing_cycle = True

    if card is not None and card["tray_status"] == "BLOCKED":
        raise api_error(
            "ERR_UNSAFE_TRAY_NO_SUBSTITUTION",
            "The resolved tray card is BLOCKED and the party cannot be seated",
        )

    if derive.find_verified_order(row["resident_id"]) is None:
        raise api_error(
            "ERR_DIET_ORDER_NOT_VERIFIED",
            "The resident no longer holds an ACTIVE and APPROVED diet order",
        )

    if missing_cycle:
        raise api_error(
            "ERR_NO_PUBLISHED_MENU_CYCLE",
            "No PUBLISHED menu cycle of the community covers %s" % row["service_date"],
        )

    row["status"] = "SEATED"
    row["seated_at"] = clock.iso()
    touch(row)

    ticket = base_row()
    ticket.update({
        "venue_id": row["venue_id"],
        "resident_id": row["resident_id"],
        "reservation_id": row["id"],
        "billed_reconciliation_id": None,
        "ticket_type": "RESIDENT",
        "service_date": row["service_date"],
        "meal_period": row["meal_period"],
        "billed_amount_cents": calc.ticket_billed_amount(
            "RESIDENT", row["meal_period"], resident
        ),
        "voided_amount_cents": 0,
        "status": "ISSUED",
        "issued_by_user_id": ctx["user_id"],
    })
    db.tickets[ticket["id"]] = ticket
    derive.recompute_guest_balance(resident)

    return ok(serialize.reservation(row))


@bp.post("/seating-reservations/<reservation_id>/release")
def release_reservation(reservation_id):
    authenticate([DSM])
    body = body_json()
    opt_str(body, "reason")

    row = get_reservation(reservation_id)
    if row["status"] not in ("RESERVED", "WAITLISTED", "SEATED"):
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a RESERVED, WAITLISTED or SEATED reservation may be released",
        )

    row["status"] = "RELEASED"
    touch(row)

    venue = db.venues.get(row["venue_id"])
    if venue is not None:
        touch(venue)
        derive.promote_waitlist(venue, row["service_date"], row["meal_period"])

    return ok(serialize.reservation(row))

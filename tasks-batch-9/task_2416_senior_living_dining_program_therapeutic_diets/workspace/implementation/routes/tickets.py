"""Meal tickets: issuance, pricing, service and voids."""
from flask import Blueprint

import serialize
from auth import authenticate
from clock import clock
from constants import MEAL_PERIODS, TICKET_STATUSES, TICKET_TYPES
from db import base_row, db, sort_created, touch
from errors import api_error
from response import created, ok, ok_list
from routes.common import (
    BS, DSM, PA, RD, SKL, get_reservation, get_resident, get_ticket, get_venue,
)
from services import calc, derive
from shape import (
    body_json, opt_str, paginate, q_date, q_enum, q_str, req_date, req_enum,
    req_str,
)

bp = Blueprint("tickets", __name__)

TICKET_READ_ROLES = [PA, RD, DSM, SKL, BS]


@bp.get("/meal-tickets/<ticket_id>")
def read_ticket(ticket_id):
    authenticate(TICKET_READ_ROLES)
    return ok(serialize.ticket(get_ticket(ticket_id)))


@bp.get("/meal-tickets")
def list_tickets():
    authenticate(TICKET_READ_ROLES)
    venue_id = q_str("venue_id")
    resident_id = q_str("resident_id")
    reservation_id = q_str("reservation_id")
    reconciliation_id = q_str("billed_reconciliation_id")
    service_date = q_date("service_date")
    meal_period = q_enum("meal_period", MEAL_PERIODS)
    ticket_type = q_enum("ticket_type", TICKET_TYPES)
    status = q_enum("status", TICKET_STATUSES)

    rows = list(db.tickets.values())
    if venue_id is not None:
        rows = [t for t in rows if t["venue_id"] == venue_id]
    if resident_id is not None:
        rows = [t for t in rows if t["resident_id"] == resident_id]
    if reservation_id is not None:
        rows = [t for t in rows if t["reservation_id"] == reservation_id]
    if reconciliation_id is not None:
        rows = [t for t in rows if t["billed_reconciliation_id"] == reconciliation_id]
    if service_date is not None:
        rows = [t for t in rows if t["service_date"] == service_date[0]]
    if meal_period is not None:
        rows = [t for t in rows if t["meal_period"] == meal_period]
    if ticket_type is not None:
        rows = [t for t in rows if t["ticket_type"] == ticket_type]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.ticket, window), pagination)


@bp.post("/meal-tickets")
def issue_ticket():
    ctx = authenticate([DSM, SKL])
    body = body_json()
    venue_id = req_str(body, "venue_id")
    ticket_type = req_enum(body, "ticket_type", TICKET_TYPES)
    service_date_str, service_date = req_date(body, "service_date")
    meal_period = req_enum(body, "meal_period", MEAL_PERIODS)
    resident_id = opt_str(body, "resident_id")
    reservation_id = opt_str(body, "reservation_id")

    venue = get_venue(venue_id)
    resident = None if resident_id is None else get_resident(resident_id)
    reservation = None if reservation_id is None else get_reservation(reservation_id)

    if resident is not None and resident["community_id"] != venue["community_id"]:
        raise api_error(
            "ERR_CROSS_COMMUNITY_REFERENCE",
            "The resident and the venue must belong to the same community",
        )

    if reservation is not None:
        if reservation["resident_id"] != resident_id or reservation["venue_id"] != venue_id:
            raise api_error(
                "ERR_LINKED_RESOURCE_MISMATCH",
                "The named reservation's resident and venue must match the payload",
            )

    if venue["status"] != "OPEN" or venue["temp_compliance_posture"] == "SUSPENDED":
        raise api_error(
            "ERR_VENUE_SERVICE_SUSPENDED",
            "The venue is not currently able to serve",
        )

    if venue["temp_compliance_posture"] == "WATCH" and ticket_type in ("GUEST", "TAKEOUT"):
        raise api_error(
            "ERR_VENUE_POSTURE_RESTRICTED",
            "A WATCH posture only permits RESIDENT tickets",
        )

    if ticket_type == "RESIDENT":
        if resident is None or derive.find_verified_order(resident_id) is None:
            raise api_error(
                "ERR_DIET_ORDER_NOT_VERIFIED",
                "A RESIDENT ticket needs a resident holding an ACTIVE and APPROVED diet order",
            )
        if resident["dining_status"] != "ACTIVE":
            raise api_error(
                "ERR_RESIDENT_NOT_ACTIVE",
                "Only an ACTIVE resident may be issued a RESIDENT ticket",
            )

    if service_date > clock.date():
        raise api_error(
            "ERR_OBSERVATION_FUTURE_DATE",
            "service_date must not fall after the logical clock date",
        )

    if derive.finalized_period_covers(venue["community_id"], service_date_str) is not None:
        raise api_error(
            "ERR_PERIOD_CLOSED",
            "A FINALIZED reconciliation already covers %s" % service_date_str,
        )

    billed_amount_cents = calc.ticket_billed_amount(ticket_type, meal_period, resident)

    if ticket_type in ("GUEST", "TAKEOUT") and resident is not None:
        community = db.communities.get(venue["community_id"])
        cap = community["guest_meal_sponsor_cap_cents"] if community is not None else 0
        projected = resident["guest_meal_charge_balance_cents"] + billed_amount_cents
        if projected > cap:
            raise api_error(
                "ERR_SPONSOR_LIMIT_EXCEEDED",
                "The sponsored balance %d would exceed the community cap %d"
                % (projected, cap),
            )

    row = base_row()
    row.update({
        "venue_id": venue_id,
        "resident_id": resident_id,
        "reservation_id": reservation_id,
        "billed_reconciliation_id": None,
        "ticket_type": ticket_type,
        "service_date": service_date_str,
        "meal_period": meal_period,
        "billed_amount_cents": billed_amount_cents,
        "voided_amount_cents": 0,
        "status": "ISSUED",
        "issued_by_user_id": ctx["user_id"],
    })
    db.tickets[row["id"]] = row

    derive.recompute_guest_balance(resident)
    return created(serialize.ticket(row))


@bp.post("/meal-tickets/<ticket_id>/serve")
def serve_ticket(ticket_id):
    authenticate([DSM, SKL])
    body_json()

    ticket = get_ticket(ticket_id)
    if ticket["status"] != "ISSUED":
        raise api_error("ERR_INVALID_STATE", "Only an ISSUED ticket may be served")

    venue = db.venues.get(ticket["venue_id"])
    if venue is not None and venue["temp_compliance_posture"] == "SUSPENDED":
        raise api_error(
            "ERR_VENUE_SERVICE_SUSPENDED",
            "A SUSPENDED venue may not serve tickets",
        )

    ticket["status"] = "SERVED"
    touch(ticket)

    if ticket["reservation_id"] is not None:
        reservation = db.reservations.get(ticket["reservation_id"])
        if reservation is not None and reservation["status"] == "SEATED":
            reservation["status"] = "COMPLETED"
            touch(reservation)

    return ok(serialize.ticket(ticket))


@bp.post("/meal-tickets/<ticket_id>/void")
def void_ticket(ticket_id):
    authenticate([BS])
    body = body_json()
    opt_str(body, "void_reason")

    ticket = get_ticket(ticket_id)
    if ticket["status"] not in ("ISSUED", "SERVED", "BILLED"):
        raise api_error("ERR_INVALID_STATE", "A VOIDED ticket cannot be voided again")

    ticket["voided_amount_cents"] = ticket["billed_amount_cents"]
    ticket["billed_amount_cents"] = 0
    ticket["status"] = "VOIDED"
    touch(ticket)

    if ticket["resident_id"] is not None:
        derive.recompute_guest_balance(db.residents.get(ticket["resident_id"]))

    if ticket["reservation_id"] is not None:
        reservation = db.reservations.get(ticket["reservation_id"])
        if reservation is not None and reservation["status"] in ("SEATED", "COMPLETED"):
            reservation["status"] = "RELEASED"
            touch(reservation)
            venue = db.venues.get(reservation["venue_id"])
            if venue is not None:
                touch(venue)
                derive.promote_waitlist(
                    venue, reservation["service_date"], reservation["meal_period"]
                )

    return ok(serialize.ticket(ticket))

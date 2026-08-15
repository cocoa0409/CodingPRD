"""ServiceTicket endpoints: create, get, list per order, schedule, resolve, reopen."""

from datetime import timedelta
from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, ApiError, ERR_ORDER_NOT_COMPLETED
from middleware import authenticate, require_roles, check_customer_owns_order
from response import success_object, success_list
from services.common import (
    new_id, get_body, require, optional, get_order, get_service_ticket,
    paginate, check_iso_date,
)
from services.pricing import SERVICE_CALL_BASE_CENTS, REOPEN_WINDOW_DAYS
from services.cascade import bump
from routes.orders import _crew_conflict
from errors import ERR_CREW_DATE_CONFLICT, ERR_DATE_IN_PAST

bp = Blueprint("tickets", __name__)

READ_ROLES = ("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
              "FinanceManager", "OperationsAdmin")


def _owns_ticket_order(ticket: dict):
    order = db.orders.get(ticket["order_id"])
    if order is not None:
        check_customer_owns_order(order)


@bp.post("/api/service-tickets")
def create_service_ticket():
    authenticate()
    require_roles("Customer", "SalesRep")
    body = get_body()
    order_id = require(body, "order_id", "str")
    issue_description = require(body, "issue_description", "str")

    order = get_order(order_id)
    check_customer_owns_order(order)

    if order["status"] not in ("COMPLETED", "CLOSED"):
        raise ApiError(ERR_ORDER_NOT_COMPLETED,
                       "Service ticket requires the order to be COMPLETED or CLOSED", 409)

    now = db.now_iso()
    ticket = {
        "id": new_id(),
        "order_id": order_id,
        "issue_description": issue_description,
        "status": "OPEN",
        "crew_id": None,
        "scheduled_date": None,
        "in_warranty": None,
        "parts_cents": 0,
        "charge_cents": None,
        "resolved_at": None,
        "reopen_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.service_tickets[ticket["id"]] = ticket
    return success_object(ticket, 201)


@bp.get("/api/service-tickets/<tid>")
def read_service_ticket(tid):
    authenticate()
    require_roles(*READ_ROLES)
    ticket = get_service_ticket(tid)
    _owns_ticket_order(ticket)
    return success_object(ticket)


@bp.get("/api/orders/<oid>/service-tickets")
def list_order_service_tickets(oid):
    authenticate()
    require_roles(*READ_ROLES)
    order = get_order(oid)
    check_customer_owns_order(order)
    rows = [t for t in db.service_tickets.values() if t["order_id"] == oid]
    rows.sort(key=lambda t: t["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/api/service-tickets/<tid>/schedule")
def schedule_service_ticket(tid):
    authenticate()
    require_roles("SalesRep")
    body = get_body()
    crew_id = require(body, "crew_id", "str")
    scheduled_date = require(body, "scheduled_date", "str")
    check_iso_date(scheduled_date, "scheduled_date")

    ticket = get_service_ticket(tid)
    if ticket["status"] != "OPEN":
        raise invalid_state("Only an OPEN ticket can be scheduled")

    # Conflict check before date check (PRD §3.8)
    if _crew_conflict(crew_id, scheduled_date):
        raise ApiError(ERR_CREW_DATE_CONFLICT,
                       "Crew already occupies the requested whole calendar date", 409)
    current_date = db.get_clock()[0:10]
    if scheduled_date < current_date:
        raise ApiError(ERR_DATE_IN_PAST, "scheduled_date before current logical date", 422)

    ticket["crew_id"] = crew_id
    ticket["scheduled_date"] = scheduled_date
    ticket["status"] = "SCHEDULED"
    bump(ticket)
    return success_object(ticket)


@bp.post("/api/service-tickets/<tid>/resolve")
def resolve_service_ticket(tid):
    authenticate()
    require_roles("InstallCrew")
    body = get_body()
    parts_cents = optional(body, "parts_cents", "int", default=0)

    ticket = get_service_ticket(tid)
    if ticket["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED ticket can be resolved")

    order = db.orders[ticket["order_id"]]
    resolved_at = db.now_iso()
    now_dt = db.parse_iso(resolved_at)
    warranty_dt = db.parse_iso(order["warranty_ends_at"])
    in_warranty = now_dt <= warranty_dt
    charge = 0 if in_warranty else SERVICE_CALL_BASE_CENTS + parts_cents

    ticket["resolved_at"] = resolved_at
    ticket["in_warranty"] = in_warranty
    ticket["parts_cents"] = parts_cents
    ticket["charge_cents"] = charge
    ticket["status"] = "RESOLVED"
    bump(ticket)
    return success_object(ticket)


@bp.post("/api/service-tickets/<tid>/reopen")
def reopen_service_ticket(tid):
    authenticate()
    require_roles("Customer")
    get_body()
    ticket = get_service_ticket(tid)
    _owns_ticket_order(ticket)

    if ticket["status"] != "RESOLVED":
        raise invalid_state("Only a RESOLVED ticket can be reopened")

    order = db.orders[ticket["order_id"]]
    now_dt = db.parse_iso(db.get_clock())
    resolved_dt = db.parse_iso(ticket["resolved_at"])
    warranty_dt = db.parse_iso(order["warranty_ends_at"])
    if now_dt > resolved_dt + timedelta(days=REOPEN_WINDOW_DAYS) or now_dt > warranty_dt:
        raise invalid_state("Reopen window expired or warranty no longer running")

    ticket["status"] = "OPEN"
    ticket["reopen_count"] += 1
    bump(ticket)
    return success_object(ticket)

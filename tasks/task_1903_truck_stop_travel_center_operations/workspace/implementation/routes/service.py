"""Shower/laundry service queue (PRD 3.5)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_MEMBER_NOT_ACTIVE,
    ERR_NOT_FOUND, ERR_NO_POINTS, ERR_QUEUE_CAPACITY, ERR_QUEUE_EMPTY,
    ERR_SHIFT_NOT_OPEN,
)
from middleware import authorized, scope_member
from response import success_object
from routes.helpers import list_response, public
from services import loyalty, pricing
from services.core import new_record, stamp, touch, adjust_shift_expected
from util import CLOCK, dec
from validate import (
    get_body, query_filter, require_path_resource, req_enum, valid_enum,
    valid_nonneg_int, valid_pos_number,
)

bp = Blueprint("service", __name__)

SERVICE_TYPES = ["SHOWER", "LAUNDRY"]
TICKET_STATUSES = ["QUEUED", "CALLED", "ACTIVE", "COMPLETED", "CANCELLED", "NO_SHOW"]
READ_ROLES = ["GeneralManager", "ShiftManager", "Cashier"]
PREEMPT_MIN_MINUTES = 15


def _capacity(site, service_type):
    return site["shower_units_count"] if service_type == "SHOWER" \
        else site["laundry_machines_count"]


def _next_queue_position(site_id, service_type):
    positions = [t["queue_position"] for t in db["service_tickets"].values()
                 if t["site_id"] == site_id and t["service_type"] == service_type]
    return (max(positions) if positions else 0) + 1


@bp.post("/sites/<sid>/service-tickets")
def create_ticket(sid):
    caller = authorized(["Cashier", "LoyaltyMember"])
    site = require_path_resource("sites", sid)
    body = get_body()

    if caller.role == "LoyaltyMember":
        scope_member(caller, body.get("loyalty_member_id"))

    # p6: body FK existence
    shift = None
    if body.get("shift_id") is not None:
        shift = db["shifts"].get(body["shift_id"]) if isinstance(body.get("shift_id"), str) else None
        if shift is None:
            raise_error(ERR_NOT_FOUND, "shift_id does not resolve")
    member = None
    if body.get("loyalty_member_id") is not None:
        member = db["loyalty_members"].get(body["loyalty_member_id"]) \
            if isinstance(body.get("loyalty_member_id"), str) else None
        if member is None:
            raise_error(ERR_NOT_FOUND, "loyalty_member_id does not resolve")

    # p9: a supplied attribution shift must be OPEN
    if shift is not None and shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "attribution shift is not OPEN")
    # p14: ticket creation requires an ACTIVE member
    if member is not None and member["status"] != "ACTIVE":
        raise_error(ERR_MEMBER_NOT_ACTIVE, "loyalty member is not ACTIVE")
    # p33: redeemable balance covers requested points
    requested = body.get("requested_redeem_points")
    if member is not None and valid_nonneg_int(requested) and requested > 0:
        if loyalty.redeemable_balance(member["id"]) < requested:
            raise_error(ERR_NO_POINTS, "requested points exceed the redeemable balance")

    # p41: final shape validation
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    if requested is not None and not valid_nonneg_int(requested):
        raise_error(ERR_INVALID_REQUEST, "requested_redeem_points must be a non-negative integer")
    requested = 0 if requested is None else requested
    if requested > 0 and member is None:
        raise_error(ERR_INVALID_REQUEST, "requested_redeem_points requires a loyalty_member_id")

    points_capped = pricing.capped_points(requested, member)
    charges = pricing.service_charges(service_type, points_capped)
    if points_capped > 0:
        loyalty.burn_fefo(member["id"], points_capped)

    rec = new_record("service_tickets", {
        "site_id": site["id"],
        "shift_id": shift["id"] if shift else None,
        "loyalty_member_id": member["id"] if member else None,
        "service_type": service_type,
        "requested_redeem_points": requested,
        "status": "QUEUED",
        "payment_status": "UNPAID",
        "queue_position": _next_queue_position(site["id"], service_type),
        "base_price_cents": charges["base_price_cents"],
        "weekend_surcharge_cents": charges["weekend_surcharge_cents"],
        "peak_surcharge_cents": charges["peak_surcharge_cents"],
        "points_discount_cents": charges["points_discount_cents"],
        "total_price_cents": charges["total_price_cents"],
        "called_at": None,
        "started_at": None,
        "completed_at": None,
        "shower_minutes": None,
        "laundry_lbs": None,
        "water_gallons": None,
        "_points_burned": points_capped,
        "_pay_tender": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/service-tickets")
def list_tickets(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "service_type": query_filter("service_type", SERVICE_TYPES),
        "status": query_filter("status", TICKET_STATUSES),
    }
    return list_response("service_tickets", filters)


@bp.get("/service-tickets/<rid>")
def get_ticket(rid):
    caller = authorized(READ_ROLES + ["LoyaltyMember"])
    rec = require_path_resource("service_tickets", rid)
    scope_member(caller, rec["loyalty_member_id"])
    return success_object(public(rec))


@bp.post("/sites/<sid>/service-queue/call")
def call_next(sid):
    authorized(["Cashier"])
    require_path_resource("sites", sid)
    body = get_body()
    service_type = body.get("service_type")
    if valid_enum(service_type, SERVICE_TYPES):
        pool = [t for t in db["service_tickets"].values()
                if t["site_id"] == sid and t["service_type"] == service_type
                and t["status"] == "QUEUED"]
        if not pool:
            raise_error(ERR_QUEUE_EMPTY, "no QUEUED ticket of that service type at the site")
        pool.sort(key=lambda t: t["queue_position"])
        ticket = pool[0]
    else:
        raise_error(ERR_INVALID_REQUEST, "service_type must be SHOWER or LAUNDRY")
    ticket["status"] = "CALLED"
    stamp(ticket, "called_at")
    touch(ticket)
    return success_object(public(ticket))


@bp.post("/service-tickets/<rid>/start")
def start_service(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("service_tickets", rid)
    if ticket["status"] != "CALLED":
        raise_error(ERR_INVALID_STATE, "ticket is not CALLED")
    site = db["sites"].get(ticket["site_id"])
    capacity = _capacity(site, ticket["service_type"])
    active = [t for t in db["service_tickets"].values()
              if t["site_id"] == ticket["site_id"]
              and t["service_type"] == ticket["service_type"]
              and t["status"] == "ACTIVE"]
    if len(active) >= capacity:
        # Preemption: longest-elapsed ACTIVE ticket (earliest started_at), ties by
        # earliest created_at; preemptable only once elapsed >= 15 minutes.
        now = CLOCK.now()
        active.sort(key=lambda t: (t.get("started_at") or "", t.get("created_at", ""),
                                   t.get("_seq", 0)))
        candidate = active[0]
        started = parse_dt_or_none(candidate.get("started_at"))
        elapsed = (now - started).total_seconds() if started is not None else 0
        if started is None or elapsed < PREEMPT_MIN_MINUTES * 60:
            raise_error(ERR_QUEUE_CAPACITY,
                        "service at capacity and no ACTIVE ticket is preemptable")
        candidate["status"] = "NO_SHOW"
        touch(candidate)
    ticket["status"] = "ACTIVE"
    stamp(ticket, "started_at")
    touch(ticket)
    return success_object(public(ticket))


def parse_dt_or_none(s):
    from util import parse_dt
    if not s:
        return None
    try:
        return parse_dt(s)
    except (ValueError, TypeError):
        return None


@bp.post("/service-tickets/<rid>/complete")
def complete_service(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("service_tickets", rid)
    if ticket["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "ticket is not ACTIVE")
    body = get_body()
    shower_minutes = body.get("shower_minutes")
    laundry_lbs = body.get("laundry_lbs")
    if ticket["service_type"] == "SHOWER":
        if not valid_pos_number(shower_minutes):
            raise_error(ERR_INVALID_REQUEST, "shower_minutes must be a positive number")
        ticket["shower_minutes"] = shower_minutes
    else:
        if not valid_pos_number(laundry_lbs):
            raise_error(ERR_INVALID_REQUEST, "laundry_lbs must be a positive number")
        ticket["laundry_lbs"] = laundry_lbs
    water = pricing.water_usage_gallons(ticket["service_type"],
                                        shower_minutes=shower_minutes,
                                        laundry_lbs=laundry_lbs)
    ticket["water_gallons"] = water
    site = db["sites"].get(ticket["site_id"])
    if site is not None:
        site["water_usage_gallons"] = float(dec(site["water_usage_gallons"]) + dec(water))
        touch(site)
    member = db["loyalty_members"].get(ticket["loyalty_member_id"]) \
        if ticket["loyalty_member_id"] else None
    loyalty.earn_points_for(member, ticket["total_price_cents"], "SERVICE", ticket["id"])
    ticket["status"] = "COMPLETED"
    stamp(ticket, "completed_at")
    touch(ticket)
    return success_object(public(ticket))


@bp.post("/service-tickets/<rid>/pay")
def pay_ticket(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("service_tickets", rid)
    body = get_body()
    # p6: optional payload shift must resolve
    shift = None
    if body.get("shift_id") is not None:
        shift = db["shifts"].get(body["shift_id"]) if isinstance(body.get("shift_id"), str) else None
        if shift is None:
            raise_error(ERR_NOT_FOUND, "shift_id does not resolve")
    if ticket["status"] not in ("CALLED", "ACTIVE", "COMPLETED"):
        raise_error(ERR_INVALID_STATE, "ticket is not payable in its current state")
    if ticket["payment_status"] != "UNPAID":
        raise_error(ERR_INVALID_STATE, "ticket payment must be UNPAID")
    tender = body.get("tender_type")
    effective_shift = shift if shift is not None else (
        db["shifts"].get(ticket["shift_id"]) if ticket["shift_id"] else None)
    if tender == "CASH":
        if effective_shift is None:
            raise_error(ERR_INVALID_REQUEST,
                        "cash payment requires a shift_id on the ticket or in the payload")
        if effective_shift["status"] != "OPEN":
            raise_error(ERR_SHIFT_NOT_OPEN, "cash payment requires an OPEN shift")
    if not valid_enum(tender, ["CASH", "CARD"]):
        raise_error(ERR_INVALID_REQUEST, "tender_type must be CASH or CARD")

    if shift is not None:
        ticket["shift_id"] = shift["id"]
    ticket["_pay_tender"] = tender
    ticket["payment_status"] = "PAID"
    if tender == "CASH":
        adjust_shift_expected(effective_shift, ticket["total_price_cents"])
    touch(ticket)
    return success_object(public(ticket))


@bp.post("/service-tickets/<rid>/cancel")
def cancel_ticket(rid):
    caller = authorized(["Cashier", "LoyaltyMember"])
    ticket = require_path_resource("service_tickets", rid)
    scope_member(caller, ticket["loyalty_member_id"])
    if ticket["status"] not in ("QUEUED", "CALLED"):
        raise_error(ERR_INVALID_STATE, "ticket cannot be cancelled from its current state")
    ticket["status"] = "CANCELLED"
    if ticket.get("_points_burned"):
        loyalty.grant_lot(ticket["loyalty_member_id"], ticket["_points_burned"],
                          "ADJUSTMENT", ticket["id"])
    if ticket["payment_status"] == "PAID":
        ticket["payment_status"] = "REFUNDED"
        if ticket.get("_pay_tender") == "CASH" and ticket.get("shift_id"):
            shift = db["shifts"].get(ticket["shift_id"])
            if shift is not None:
                adjust_shift_expected(shift, -ticket["total_price_cents"])
    touch(ticket)
    return success_object(public(ticket))


@bp.post("/service-tickets/<rid>/no-show")
def ticket_no_show(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("service_tickets", rid)
    if ticket["status"] != "CALLED":
        raise_error(ERR_INVALID_STATE, "ticket is not CALLED")
    ticket["status"] = "NO_SHOW"
    touch(ticket)
    return success_object(public(ticket))


@bp.post("/service-tickets/<rid>/requeue")
def requeue_ticket(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("service_tickets", rid)
    if ticket["status"] != "NO_SHOW":
        raise_error(ERR_INVALID_STATE, "ticket is not NO_SHOW")
    ticket["status"] = "QUEUED"
    ticket["queue_position"] = _next_queue_position(ticket["site_id"], ticket["service_type"])
    touch(ticket)
    return success_object(public(ticket))

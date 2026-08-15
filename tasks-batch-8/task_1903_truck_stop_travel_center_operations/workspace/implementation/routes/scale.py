"""Certified scale tickets and weigh events (PRD 3.5)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_FORBIDDEN, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_NOT_FOUND, ERR_SCALE_NOT_CERTIFIABLE, ERR_SHIFT_NOT_OPEN,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_from, list_response, public
from services import pricing
from services.core import new_record, touch, adjust_shift_expected
from validate import (
    get_body, query_filter, require_path_resource, req_bool, req_enum, req_int,
    req_str, valid_enum,
)

bp = Blueprint("scale", __name__)

SCALE_STATUSES = ["OPEN", "PAID", "CLOSED", "CANCELLED", "REFUNDED"]
WEIGH_KINDS = ["GROSS", "TARE", "REWEIGH"]
READ_ROLES = ["GeneralManager", "ShiftManager", "Cashier"]


@bp.post("/sites/<sid>/scale-tickets")
def create_scale_ticket(sid):
    authorized(["Cashier"])
    require_path_resource("sites", sid)
    body = get_body()
    # p6: shift FK existence
    shift = None
    if body.get("shift_id") is not None:
        shift = db["shifts"].get(body["shift_id"]) if isinstance(body.get("shift_id"), str) else None
        if shift is None:
            raise_error(ERR_NOT_FOUND, "shift_id does not resolve")
    # p9: attribution shift must be OPEN
    if shift is not None and shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "attribution shift is not OPEN")
    if shift is None:
        raise_error(ERR_INVALID_REQUEST, "shift_id is required")
    plate = req_str(body, "vehicle_plate")
    carrier = req_str(body, "carrier_name")
    certified = req_bool(body, "certified")
    rec = new_record("scale_tickets", {
        "site_id": sid,
        "shift_id": shift["id"],
        "vehicle_plate": plate,
        "carrier_name": carrier,
        "certified": certified,
        "status": "OPEN",
        "reweigh_count": 0,
        "gross_lbs": None,
        "tare_lbs": None,
        "net_lbs": None,
        "total_paid_cents": 0,
        "refund_total_cents": 0,
        "_pay_tender": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/scale-tickets")
def list_scale_tickets(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "status": query_filter("status", SCALE_STATUSES),
    }
    return list_response("scale_tickets", filters)


@bp.get("/scale-tickets/<rid>")
def get_scale_ticket(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("scale_tickets", rid)
    return success_object(public(rec))


@bp.post("/scale-tickets/<rid>/weigh")
def weigh(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("scale_tickets", rid)
    if ticket["status"] not in ("OPEN", "PAID"):
        raise_error(ERR_INVALID_STATE, "ticket does not accept weigh events in its current state")
    body = get_body()
    kind = req_enum(body, "weigh_kind", WEIGH_KINDS)
    weight = req_int(body, "weight_lbs", positive=True)
    seq = len([e for e in db["weigh_events"].values() if e["scale_ticket_id"] == ticket["id"]]) + 1
    event = new_record("weigh_events", {
        "scale_ticket_id": ticket["id"],
        "weigh_kind": kind,
        "weight_lbs": weight,
        "sequence": seq,
    }, ledger=True)
    if kind in ("GROSS", "REWEIGH"):
        ticket["gross_lbs"] = weight
    elif kind == "TARE":
        ticket["tare_lbs"] = weight
    if kind == "REWEIGH":
        ticket["reweigh_count"] += 1
    if ticket["gross_lbs"] is not None and ticket["tare_lbs"] is not None:
        ticket["net_lbs"] = ticket["gross_lbs"] - ticket["tare_lbs"]
    touch(ticket)
    return success_object(public(event), status=201)


@bp.get("/scale-tickets/<rid>/weigh-events")
def weigh_events(rid):
    authorized(READ_ROLES)
    ticket = require_path_resource("scale_tickets", rid)
    events = [e for e in db["weigh_events"].values() if e["scale_ticket_id"] == ticket["id"]]
    return list_from(events)


@bp.post("/scale-tickets/<rid>/settle")
def settle(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("scale_tickets", rid)
    body = get_body()
    if ticket["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "ticket is not OPEN")
    # p9: CASH tender requires the ticket's shift to be OPEN
    tender = body.get("tender_type")
    shift = db["shifts"].get(ticket["shift_id"])
    if tender == "CASH" and (shift is None or shift["status"] != "OPEN"):
        raise_error(ERR_SHIFT_NOT_OPEN, "cash settlement requires an OPEN shift")
    # p30: at least one GROSS and one TARE event
    kinds = {e["weigh_kind"] for e in db["weigh_events"].values()
             if e["scale_ticket_id"] == ticket["id"]}
    if "GROSS" not in kinds or "TARE" not in kinds:
        raise_error(ERR_SCALE_NOT_CERTIFIABLE,
                    "settle requires at least one GROSS and one TARE weigh event")
    if not valid_enum(tender, ["CASH", "CARD"]):
        raise_error(ERR_INVALID_REQUEST, "tender_type must be CASH or CARD")
    charge = pricing.scale_charge_cents(ticket["certified"])
    ticket["total_paid_cents"] = charge
    ticket["_pay_tender"] = tender
    ticket["status"] = "PAID"
    if tender == "CASH":
        adjust_shift_expected(shift, charge)
    touch(ticket)
    return success_object(public(ticket))


@bp.post("/scale-tickets/<rid>/close")
def close_ticket(rid):
    authorized(["Cashier"])
    ticket = require_path_resource("scale_tickets", rid)
    if ticket["status"] != "PAID":
        raise_error(ERR_INVALID_STATE, "ticket is not PAID")
    ticket["status"] = "CLOSED"
    touch(ticket)
    return success_object(public(ticket))


@bp.post("/scale-tickets/<rid>/cancel")
def cancel_ticket(rid):
    caller = authorized(["Cashier", "ShiftManager"])
    ticket = require_path_resource("scale_tickets", rid)
    if ticket["status"] == "OPEN":
        if ticket["total_paid_cents"] != 0:
            raise_error(ERR_INVALID_STATE, "open ticket with charges cannot be cancelled")
        ticket["status"] = "CANCELLED"
        touch(ticket)
        return success_object(public(ticket))
    if ticket["status"] == "PAID":
        if caller.role != "ShiftManager":
            raise_error(ERR_FORBIDDEN, "cancelling a paid scale ticket is a shift-manager action")
        ticket["status"] = "REFUNDED"
        ticket["refund_total_cents"] += ticket["total_paid_cents"]
        if ticket.get("_pay_tender") == "CASH":
            shift = db["shifts"].get(ticket["shift_id"])
            if shift is not None:
                adjust_shift_expected(shift, -ticket["total_paid_cents"])
        touch(ticket)
        return success_object(public(ticket))
    raise_error(ERR_INVALID_STATE, "ticket cannot be cancelled from its current state")

"""Break/fix service dispatch endpoints (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

import calc
import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_device, get_technician, get_ticket
from store import db, new_row, touch
from util import ceil_hours, overlaps

bp = Blueprint("tickets", __name__)

SEVERITIES = ("CRITICAL", "STANDARD")
CANCELLABLE = ("OPEN", "DISPATCHED", "PARTS_HOLD")


@bp.post("/service-tickets")
def create_ticket():
    user_id, _role = require("CustomerAdmin")
    body = v.body()
    device_id = v.id_field(body, "device_id")
    severity = v.enum_field(body, "severity", SEVERITIES)
    symptom_code = v.string_field(body, "symptom_code")
    part_sku = v.string_field(body, "part_sku", required=False, default=None)
    device = get_device(device_id)

    contract = derive.device_contract(device)
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The governing contract is not ACTIVE.")
    if user_id != device["site_id"]:
        fail("ERR_SITE_OWNERSHIP_REQUIRED",
             "A CustomerAdmin may only raise tickets for devices at its own site.")

    if severity == "CRITICAL":
        sla_hours = contract["response_sla_hours_critical"]
    else:
        sla_hours = contract["response_sla_hours_standard"]

    row = new_row()
    row.update({
        "device_id": device["id"],
        "assigned_technician_id": None,
        "severity": severity,
        "status": "OPEN",
        "symptom_code": symptom_code,
        "part_sku": part_sku,
        "opened_at": db.clock,
        "respond_by": db.clock + timedelta(hours=sla_hours),
        "window_start": None,
        "window_end": None,
        "hold_started_at": None,
        "parts_hold_hours": 0,
        "responded_at": None,
        "hours_late": 0,
        "labor_hours": 0,
        "labor_cents": 0,
        "sla_credit_cents": 0,
    })
    db.tickets[row["id"]] = row
    return created(serialize.ticket(row))


@bp.get("/service-tickets/<ticket_id>")
def read_ticket(ticket_id):
    require("FleetOpsController", "FieldTechnician", "CustomerAdmin",
            "BillingAnalyst", "AccountManager")
    ticket = get_ticket(ticket_id)
    return ok(serialize.ticket(ticket))


@bp.get("/service-tickets")
def list_tickets():
    require("FleetOpsController", "FieldTechnician", "CustomerAdmin",
            "BillingAnalyst", "AccountManager")
    rows = db.sorted_rows("tickets")
    for field in ("device_id", "assigned_technician_id", "status", "severity"):
        value = v.query_filter(field)
        if value is not None:
            rows = [t for t in rows if t[field] == value]
    data, meta = v.paginate(rows, serialize.ticket)
    return ok_list(data, meta)


@bp.post("/service-tickets/<ticket_id>/dispatch")
def dispatch_ticket(ticket_id):
    require("FleetOpsController")
    ticket = get_ticket(ticket_id)
    body = v.body()
    technician_id = v.id_field(body, "technician_id")
    window_start = v.dt_field(body, "window_start")
    window_end = v.dt_field(body, "window_end")
    technician = get_technician(technician_id)

    if ticket["status"] != "OPEN":
        fail("ERR_TICKET_INVALID_STATE",
             "A ticket in %s cannot be dispatched." % ticket["status"])
    if ticket["severity"] == "CRITICAL" and technician["skill_level"] not in ("L2", "L3"):
        fail("ERR_TECHNICIAN_NOT_CERTIFIED",
             "A CRITICAL ticket requires an L2 or L3 technician.")
    device = db.devices.get(ticket["device_id"])
    site = derive.device_site(device) if device is not None else None
    if site is None or technician["home_region"] != site["address_region"]:
        fail("ERR_TECHNICIAN_REGION_MISMATCH",
             "The technician's home_region does not match the site's address_region.")
    if window_start >= window_end:
        fail("ERR_DISPATCH_WINDOW_CONFLICT",
             "window_start must be strictly earlier than window_end.")
    if window_start < db.clock:
        fail("ERR_DISPATCH_WINDOW_CONFLICT",
             "window_start must be at or after the logical clock.")
    buffer_delta = timedelta(minutes=technician["travel_buffer_minutes"])
    for other in db.tickets.values():
        if other["id"] == ticket["id"]:
            continue
        if other["assigned_technician_id"] != technician["id"]:
            continue
        if other["status"] not in derive.IN_FLIGHT_TICKET_STATES:
            continue
        if other["window_start"] is None or other["window_end"] is None:
            continue
        if overlaps(window_start, window_end,
                    other["window_start"] - buffer_delta,
                    other["window_end"] + buffer_delta):
            fail("ERR_DISPATCH_WINDOW_CONFLICT",
                 "The window intersects a buffered window already occupied by the technician.")

    ticket["status"] = "DISPATCHED"
    ticket["assigned_technician_id"] = technician["id"]
    ticket["window_start"] = window_start
    ticket["window_end"] = window_end
    touch(ticket)
    if device is not None and device["lifecycle_state"] == "ACTIVE":
        device["lifecycle_state"] = "SERVICE_HOLD"
        touch(device)
    return ok(serialize.ticket(ticket))


def _require_assigned(ticket, user_id):
    if ticket["assigned_technician_id"] != user_id:
        fail("ERR_TECHNICIAN_NOT_ASSIGNED",
             "Only the assigned technician may advance this ticket.")


@bp.post("/service-tickets/<ticket_id>/parts-hold")
def parts_hold(ticket_id):
    user_id, _role = require("FieldTechnician")
    ticket = get_ticket(ticket_id)
    v.body()
    if ticket["status"] != "DISPATCHED":
        fail("ERR_TICKET_INVALID_STATE",
             "A ticket in %s cannot enter PARTS_HOLD." % ticket["status"])
    _require_assigned(ticket, user_id)
    device = db.devices.get(ticket["device_id"])
    if ticket["part_sku"] is None:
        fail("ERR_PART_IS_AVAILABLE", "The ticket does not name a part_sku.")
    row = derive.stock_row(device["site_id"], ticket["part_sku"]) if device else None
    if row is not None and row["on_hand_qty"] > 0:
        fail("ERR_PART_IS_AVAILABLE",
             "The required part is in the site locker; a parts hold is not legitimate.")
    ticket["status"] = "PARTS_HOLD"
    ticket["hold_started_at"] = db.clock
    touch(ticket)
    return ok(serialize.ticket(ticket))


@bp.post("/service-tickets/<ticket_id>/arrive-onsite")
def arrive_onsite(ticket_id):
    user_id, _role = require("FieldTechnician")
    ticket = get_ticket(ticket_id)
    v.body()
    if ticket["status"] not in ("DISPATCHED", "PARTS_HOLD"):
        fail("ERR_TICKET_INVALID_STATE",
             "A ticket in %s cannot record arrival." % ticket["status"])
    _require_assigned(ticket, user_id)
    device = db.devices.get(ticket["device_id"])
    row = None
    if ticket["part_sku"] is not None:
        row = derive.stock_row(device["site_id"], ticket["part_sku"]) if device else None
        if row is None or row["on_hand_qty"] < 1:
            fail("ERR_PART_NOT_AVAILABLE",
                 "The required part is not on hand at the device's site.")

    if ticket["status"] == "PARTS_HOLD" and ticket["hold_started_at"] is not None:
        ticket["parts_hold_hours"] += ceil_hours(db.clock - ticket["hold_started_at"])
        ticket["hold_started_at"] = None
    if row is not None:
        row["on_hand_qty"] -= 1
        touch(row)
    ticket["status"] = "ONSITE"
    touch(ticket)
    return ok(serialize.ticket(ticket))


@bp.post("/service-tickets/<ticket_id>/resolve")
def resolve_ticket(ticket_id):
    user_id, _role = require("FieldTechnician")
    ticket = get_ticket(ticket_id)
    body = v.body()
    labor_hours = v.number_field(body, "labor_hours", minimum=0)
    if ticket["status"] != "ONSITE":
        fail("ERR_TICKET_INVALID_STATE",
             "A ticket in %s cannot be resolved." % ticket["status"])
    _require_assigned(ticket, user_id)
    if labor_hours > 8:
        fail("ERR_LABOR_HOURS_EXCEED_LIMIT",
             "Reported labor_hours may not exceed 8 hours per ticket.")

    device = db.devices.get(ticket["device_id"])
    contract = derive.device_contract(device) if device is not None else None
    ticket["status"] = "RESOLVED"
    ticket["responded_at"] = db.clock
    ticket["labor_hours"] = labor_hours
    ticket["hours_late"] = ceil_hours(db.clock - ticket["respond_by"])
    if contract is not None:
        ticket["labor_cents"] = calc.service_labor_charge(ticket, contract)
        ticket["sla_credit_cents"] = calc.sla_response_credit(ticket, contract)
    touch(ticket)
    if device is not None and device["lifecycle_state"] == "SERVICE_HOLD":
        device["lifecycle_state"] = "ACTIVE"
        touch(device)
    return ok(serialize.ticket(ticket))


@bp.post("/service-tickets/<ticket_id>/cancel")
def cancel_ticket(ticket_id):
    user_id, _role = require("CustomerAdmin")
    ticket = get_ticket(ticket_id)
    v.body()
    if ticket["status"] not in CANCELLABLE:
        fail("ERR_TICKET_INVALID_STATE",
             "A ticket in %s cannot be cancelled." % ticket["status"])
    device = db.devices.get(ticket["device_id"])
    if device is None or user_id != device["site_id"]:
        fail("ERR_SITE_OWNERSHIP_REQUIRED",
             "A CustomerAdmin may only cancel tickets for devices at its own site.")
    ticket["status"] = "CANCELLED"
    touch(ticket)
    if device["lifecycle_state"] == "SERVICE_HOLD":
        if not derive.device_in_flight_tickets(device["id"]):
            device["lifecycle_state"] = "ACTIVE"
            touch(device)
    return ok(serialize.ticket(ticket))

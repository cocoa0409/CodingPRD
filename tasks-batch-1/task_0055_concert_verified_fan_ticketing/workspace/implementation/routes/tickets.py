"""Ticket routes incl. mobile-only scan (PRD §3.5)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NON_MOBILE_ENTRY,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, require_str, sorted_by_creation

bp = Blueprint("tickets", __name__)


@bp.get("/tickets/<tid>")
def get_ticket(tid):
    require_auth(["Fan", "PromoterAdmin", "GateScanner"])()
    ticket = get_or_404(db.tickets, tid, "Ticket")
    return ok_object(ticket, 200)


@bp.get("/tickets")
def list_tickets():
    require_auth(["Fan", "PromoterAdmin", "GateScanner"])()
    limit, offset = paginate_params(request.args)
    order_id = request.args.get("order_id")
    event_id = request.args.get("event_id")
    holder_fan_id = request.args.get("holder_fan_id")
    entry_status = request.args.get("entry_status")
    holding_status = request.args.get("holding_status")
    items = list(db.tickets.values())
    if order_id is not None:
        items = [t for t in items if t.get("order_id") == order_id]
    if event_id is not None:
        items = [t for t in items if t.get("event_id") == event_id]
    if holder_fan_id is not None:
        items = [t for t in items if t.get("holder_fan_id") == holder_fan_id]
    if entry_status is not None:
        items = [t for t in items if t.get("entry_status") == entry_status]
    if holding_status is not None:
        items = [t for t in items if t.get("holding_status") == holding_status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.post("/tickets/<tid>/scan")
def scan_ticket(tid):
    require_auth(["GateScanner"])()
    ticket = get_or_404(db.tickets, tid, "Ticket")
    body = get_json_body()
    device_channel = require_str(body, "device_channel")

    event = db.events.get(ticket.get("event_id"))

    # priority 5: state — VALID, holding not TRANSFER_PENDING/LISTED, event phase.
    if ticket["entry_status"] != "VALID":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket entry_status is not VALID")
    if ticket["holding_status"] in ("TRANSFER_PENDING", "LISTED"):
        raise APIError(ERR_INVALID_STATE, 409, "Ticket is mid-transfer or listed")
    if event is None or event["sales_status"] not in ("GENERAL", "SOLD_OUT", "CLOSED"):
        raise APIError(ERR_INVALID_STATE, 409, "Event not in an entry-eligible phase")

    # priority 8: mobile-only entry
    if device_channel != "MOBILE":
        raise APIError(ERR_NON_MOBILE_ENTRY, 422, "Mobile-only entry")

    ticket["entry_status"] = "SCANNED"
    db.bump(ticket)
    return ok_object(ticket, 200)

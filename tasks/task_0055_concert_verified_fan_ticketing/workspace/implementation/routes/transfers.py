"""Transfer routes (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE,
    ERR_FAN_FLAGGED,
    ERR_FAN_NOT_VERIFIED,
    ERR_SELF_DEALING,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, require_str, sorted_by_creation

bp = Blueprint("transfers", __name__)


@bp.post("/transfers")
def create_transfer():
    require_auth(["Fan"])()
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    sender_fan_id = require_str(body, "sender_fan_id")
    recipient_fan_id = require_str(body, "recipient_fan_id")

    # existence (ticket, then fans)
    ticket = get_or_404(db.tickets, ticket_id, "Ticket")
    sender = get_or_404(db.fans, sender_fan_id, "Fan")
    recipient = get_or_404(db.fans, recipient_fan_id, "Fan")

    # ownership: acting fan == sender; sender must hold the ticket
    if g.user_id != sender_fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the sender")
    if ticket.get("holder_fan_id") != sender_fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Sender does not hold this ticket")

    # state: ticket HELD + VALID
    if ticket["holding_status"] != "HELD" or ticket["entry_status"] != "VALID":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket not HELD/VALID")

    # priority 6: flag bar (sender / acting fan)
    if sender["verification_status"] == "FLAGGED":
        raise APIError(ERR_FAN_FLAGGED, 403, "Fan is flagged")
    # priority 9: verified (sender / acting fan)
    if sender["verification_status"] != "VERIFIED":
        raise APIError(ERR_FAN_NOT_VERIFIED, 422, "Fan is not verified")
    # priority 10: self-dealing
    if recipient_fan_id == sender_fan_id:
        raise APIError(ERR_SELF_DEALING, 422, "recipient equals sender")

    transfer = db.stamp_common(
        {
            "ticket_id": ticket_id,
            "sender_fan_id": sender_fan_id,
            "recipient_fan_id": recipient_fan_id,
            "status": "PENDING",
        }
    )
    db.transfers[transfer["id"]] = transfer

    ticket["holding_status"] = "TRANSFER_PENDING"
    db.bump(ticket)
    return ok_object(transfer, 201)


@bp.post("/transfers/<xid>/accept")
def accept_transfer(xid):
    require_auth(["Fan"])()
    transfer = get_or_404(db.transfers, xid, "Transfer")
    recipient = db.fans.get(transfer["recipient_fan_id"])

    # ownership: acting fan == recipient
    if g.user_id != transfer["recipient_fan_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the recipient")
    # state
    if transfer["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Transfer not PENDING")
    ticket = db.tickets.get(transfer["ticket_id"])
    if ticket is None or ticket["holding_status"] != "TRANSFER_PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket not TRANSFER_PENDING")

    # priority 6: flag bar (recipient / acting fan)
    if recipient is not None and recipient["verification_status"] == "FLAGGED":
        raise APIError(ERR_FAN_FLAGGED, 403, "Fan is flagged")
    # priority 9: verified (recipient / acting fan)
    if recipient is None or recipient["verification_status"] != "VERIFIED":
        raise APIError(ERR_FAN_NOT_VERIFIED, 422, "Recipient is not verified")

    transfer["status"] = "ACCEPTED"
    db.bump(transfer)
    ticket["holder_fan_id"] = transfer["recipient_fan_id"]
    ticket["holding_status"] = "HELD"
    db.bump(ticket)
    return ok_object(transfer, 200)


@bp.post("/transfers/<xid>/decline")
def decline_transfer(xid):
    require_auth(["Fan"])()
    transfer = get_or_404(db.transfers, xid, "Transfer")

    if g.user_id != transfer["recipient_fan_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the recipient")
    if transfer["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Transfer not PENDING")

    transfer["status"] = "DECLINED"
    db.bump(transfer)
    ticket = db.tickets.get(transfer["ticket_id"])
    if ticket is not None:
        ticket["holding_status"] = "HELD"
        db.bump(ticket)
    return ok_object(transfer, 200)


@bp.post("/transfers/<xid>/cancel")
def cancel_transfer(xid):
    require_auth(["Fan"])()
    transfer = get_or_404(db.transfers, xid, "Transfer")

    if g.user_id != transfer["sender_fan_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the sender")
    if transfer["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Transfer not PENDING")

    transfer["status"] = "CANCELLED"
    db.bump(transfer)
    ticket = db.tickets.get(transfer["ticket_id"])
    if ticket is not None:
        ticket["holding_status"] = "HELD"
        db.bump(ticket)
    return ok_object(transfer, 200)


@bp.get("/transfers/<xid>")
def get_transfer(xid):
    require_auth(["Fan", "PromoterAdmin"])()
    transfer = get_or_404(db.transfers, xid, "Transfer")
    return ok_object(transfer, 200)


@bp.get("/transfers")
def list_transfers():
    require_auth(["Fan", "PromoterAdmin"])()
    limit, offset = paginate_params(request.args)
    ticket_id = request.args.get("ticket_id")
    sender_fan_id = request.args.get("sender_fan_id")
    recipient_fan_id = request.args.get("recipient_fan_id")
    status = request.args.get("status")
    items = list(db.transfers.values())
    if ticket_id is not None:
        items = [t for t in items if t.get("ticket_id") == ticket_id]
    if sender_fan_id is not None:
        items = [t for t in items if t.get("sender_fan_id") == sender_fan_id]
    if recipient_fan_id is not None:
        items = [t for t in items if t.get("recipient_fan_id") == recipient_fan_id]
    if status is not None:
        items = [t for t in items if t.get("status") == status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)

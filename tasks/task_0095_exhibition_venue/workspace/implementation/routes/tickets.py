"""Ticket routes (§3.7)."""

from flask import Blueprint, g

import response as resp
from middleware import require_roles
from services import ticket_service
from services.common import serialize


bp = Blueprint("tickets", __name__)


@bp.route("/exhibitions/<exhibition_id>/tickets", methods=["POST"])
def issue_ticket(exhibition_id):
    require_roles("VenueAdmin", "VenueOps", "Exhibitor")
    row = ticket_service.issue_ticket(exhibition_id, g.body)
    return resp.created(serialize(row))


@bp.route("/tickets/<ticket_id>/scan-in", methods=["POST"])
def scan_in(ticket_id):
    require_roles("GateOperator")
    row = ticket_service.scan_in(ticket_id, g.body)
    return resp.success(serialize(row))


@bp.route("/tickets/<ticket_id>/scan-out", methods=["POST"])
def scan_out(ticket_id):
    require_roles("GateOperator")
    row = ticket_service.scan_out(ticket_id, g.body)
    return resp.success(serialize(row))


@bp.route("/tickets/<ticket_id>/refund", methods=["POST"])
def refund(ticket_id):
    require_roles("VenueAdmin")
    row = ticket_service.refund_ticket(ticket_id, g.body)
    return resp.success(serialize(row))


@bp.route("/tickets/<ticket_id>/void", methods=["POST"])
def void(ticket_id):
    require_roles("VenueAdmin")
    row = ticket_service.void_ticket(ticket_id, g.body)
    return resp.success(serialize(row))

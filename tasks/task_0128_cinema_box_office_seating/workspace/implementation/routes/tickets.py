"""Ticket reverse-reachability reads (SCAFFOLD §1.5).

GET /tickets/{id} and GET /tickets filterable by member_id, showtime_id, seat_id,
state. Members may only read their own tickets.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize, current_role, current_user_id,
    BOX_OFFICE_AGENT, MEMBER, CINEMA_MANAGER,
)
import response
from services import common as C
from routes._helpers import get_or_404, require_member_owns_resource

bp = Blueprint("tickets", __name__)


@bp.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER, CINEMA_MANAGER})
    ticket = get_or_404(db.tickets, ticket_id, "Ticket")
    require_member_owns_resource(ticket["member_id"])
    return response.ok_object(C.serialize(ticket), 200)


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER, CINEMA_MANAGER})
    limit, offset = C.parse_pagination()
    member_id = request.args.get("member_id")
    showtime_id = request.args.get("showtime_id")
    seat_id = request.args.get("seat_id")
    state = request.args.get("state")
    items = list(db.tickets.values())
    if current_role() == MEMBER:
        items = [t for t in items if t["member_id"] == current_user_id()]
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    if showtime_id is not None:
        items = [t for t in items if t["showtime_id"] == showtime_id]
    if seat_id is not None:
        items = [t for t in items if t["seat_id"] == seat_id]
    if state is not None:
        items = [t for t in items if t["state"] == state]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)

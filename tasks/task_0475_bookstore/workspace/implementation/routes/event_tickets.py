"""Event ticket reads, check-in, refund."""
from flask import Blueprint, request

from common import json_body, touch, parse_pagination, paginate
from db import db
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authorize, check_owner
from response import success_object, success_list
from serialize import event_ticket_out
from services import (recompute_event_tickets_sold, recompute_member_balances,
                      append_ledger)

bp = Blueprint("event_tickets", __name__)

READ_ROLES = {"Member", "Bookseller", "StoreAdmin"}
STAFF_ROLES = {"Bookseller", "StoreAdmin"}
MEMBER_ADMIN = {"Member", "StoreAdmin"}


def _find(tid):
    t = db.event_tickets.get(tid)
    if t is None:
        raise err(ERR_NOT_FOUND, "Event ticket not found")
    return t


@bp.route("/event-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    user_id, role = authorize(READ_ROLES)
    t = _find(tid)
    check_owner(user_id, role, t["member_id"])
    return success_object(event_ticket_out(t), status=200)


@bp.route("/event-tickets", methods=["GET"])
def list_tickets():
    user_id, role = authorize(READ_ROLES)
    member_id = request.args.get("member_id")
    event_id = request.args.get("event_id")
    state = request.args.get("state")
    items = list(db.event_tickets.values())
    if role == "Member":
        items = [t for t in items if t["member_id"] == user_id]
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    if event_id is not None:
        items = [t for t in items if t["event_id"] == event_id]
    if state is not None:
        items = [t for t in items if t["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([event_ticket_out(t) for t in page], limit, offset, total)


@bp.route("/event-tickets/<tid>/check-in", methods=["POST"])
def check_in(tid):
    authorize(STAFF_ROLES)
    t = _find(tid)
    json_body(optional=True)
    if t["state"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "Ticket is not BOOKED")
    # cross-entity guard: event must still be SCHEDULED
    event = db.author_events.get(t["event_id"])
    if event is None or event["state"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Event is not SCHEDULED")
    t["state"] = "CHECKED_IN"
    touch(t)
    return success_object(event_ticket_out(t), status=200)


@bp.route("/event-tickets/<tid>/refund", methods=["POST"])
def refund(tid):
    user_id, role = authorize(MEMBER_ADMIN)
    t = _find(tid)
    check_owner(user_id, role, t["member_id"])
    json_body(optional=True)
    if t["state"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "Ticket is not BOOKED")
    append_ledger(t["member_id"], t["price_paid_cents"], "EVENT_REFUND", t["id"])
    member = db.members.get(t["member_id"])
    if member is not None:
        recompute_member_balances(member)
    t["state"] = "REFUNDED"
    touch(t)
    event = db.author_events.get(t["event_id"])
    if event is not None:
        recompute_event_tickets_sold(event, mutate=True)
    return success_object(event_ticket_out(t), status=200)

"""Author events and ticket booking."""
from flask import Blueprint, request

from clock import clock
from common import (json_body, make_record, touch, get_str, get_int,
                    parse_pagination, paginate)
from datetime_util import parse_iso8601, format_iso8601
from db import db
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_EVENT_PAST,
                    ERR_EVENT_SOLD_OUT)
from middleware import authorize, check_owner
from response import success_object, success_list
from serialize import author_event_out, event_ticket_out
from services import (recompute_event_tickets_sold, recompute_member_balances,
                      append_ledger)
from calculations import ticket_price

bp = Blueprint("author_events", __name__)

STAFF_ROLES = {"Bookseller", "StoreAdmin"}
READ_ROLES = {"Member", "Bookseller", "StoreAdmin"}
BOOK_ROLES = {"Member", "Bookseller", "StoreAdmin"}


def _find(eid):
    e = db.author_events.get(eid)
    if e is None:
        raise err(ERR_NOT_FOUND, "Author event not found")
    return e


@bp.route("/author-events", methods=["POST"])
def create_event():
    authorize(STAFF_ROLES)
    body = json_body(optional=False)
    title_id = get_str(body, "title_id", required=True)
    name = get_str(body, "name", required=True)
    starts_at_raw = get_str(body, "starts_at", required=True)
    starts_at = parse_iso8601(starts_at_raw)
    capacity = get_int(body, "capacity", required=True, minimum=1)
    base_price_cents = get_int(body, "base_price_cents", required=True, minimum=0)
    if title_id not in db.titles:
        raise err(ERR_NOT_FOUND, "Title not found")
    rec = make_record({
        "title_id": title_id,
        "name": name,
        "starts_at": format_iso8601(starts_at),
        "capacity": capacity,
        "base_price_cents": base_price_cents,
        "tickets_sold": 0,
        "state": "SCHEDULED",
    })
    db.author_events[rec["id"]] = rec
    return success_object(author_event_out(rec), status=201)


@bp.route("/author-events/<eid>", methods=["GET"])
def get_event(eid):
    authorize(READ_ROLES)
    e = _find(eid)
    return success_object(author_event_out(e), status=200)


@bp.route("/author-events", methods=["GET"])
def list_events():
    authorize(READ_ROLES)
    title_id = request.args.get("title_id")
    state = request.args.get("state")
    items = list(db.author_events.values())
    if title_id is not None:
        items = [e for e in items if e["title_id"] == title_id]
    if state is not None:
        items = [e for e in items if e["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([author_event_out(e) for e in page], limit, offset, total)


@bp.route("/author-events/<eid>/tickets", methods=["POST"])
def book_ticket(eid):
    user_id, role = authorize(BOOK_ROLES)
    e = _find(eid)
    body = json_body(optional=False)
    member_id = get_str(body, "member_id", required=True)
    check_owner(user_id, role, member_id)
    if member_id not in db.members:
        raise err(ERR_NOT_FOUND, "Member not found")
    member = db.members[member_id]
    title = db.titles[e["title_id"]]

    # business checks: event must start strictly after now, then seat available
    event_start = parse_iso8601(e["starts_at"])
    if not (event_start > clock.now()):
        raise err(ERR_EVENT_PAST, "Event does not start strictly after now")
    recompute_event_tickets_sold(e, mutate=False)
    if e["tickets_sold"] >= e["capacity"]:
        raise err(ERR_EVENT_SOLD_OUT, "Event is sold out")

    price = ticket_price(e["base_price_cents"], title["demand_flag"], member["tier"])
    ticket = make_record({
        "event_id": eid,
        "member_id": member_id,
        "price_paid_cents": price,
        "state": "BOOKED",
    })
    db.event_tickets[ticket["id"]] = ticket
    recompute_event_tickets_sold(e, mutate=True)
    return success_object(event_ticket_out(ticket), status=201)


@bp.route("/author-events/<eid>/tickets", methods=["GET"])
def list_event_tickets(eid):
    authorize(STAFF_ROLES)
    e = _find(eid)
    state = request.args.get("state")
    items = [t for t in db.event_tickets.values() if t["event_id"] == eid]
    if state is not None:
        items = [t for t in items if t["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([event_ticket_out(t) for t in page], limit, offset, total)


@bp.route("/author-events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    authorize(STAFF_ROLES)
    e = _find(eid)
    json_body(optional=True)
    if e["state"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Event is not SCHEDULED")
    # cascade: refund every BOOKED ticket
    for t in db.event_tickets.values():
        if t["event_id"] == eid and t["state"] == "BOOKED":
            t["state"] = "REFUNDED"
            touch(t)
            append_ledger(t["member_id"], t["price_paid_cents"], "EVENT_REFUND", t["id"])
            member = db.members.get(t["member_id"])
            if member is not None:
                recompute_member_balances(member)
    recompute_event_tickets_sold(e, mutate=True)
    e["state"] = "CANCELLED"
    touch(e)
    return success_object(author_event_out(e), status=200)

"""QueueTicket routes: take a walk-in ticket, read/list, cancel
(PRD §3.5; SCAFFOLD §1.5). Seating lives in venues.py (seat_next)."""

from flask import Blueprint, request

from db import db, stamp_common, touch
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles, require_owner
from errors import raise_err, ERR_INVALID_STATE
from services import validate as V
from services.lookup import get_or_404
from services.serialize import queue_ticket_out

bp = Blueprint("queue_tickets", __name__)


@bp.post("/golf/queue-tickets")
def create_queue_ticket():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk"})
    data = V.body()

    venue_id = V.as_str(V.require(data, "venue_id"), "venue_id")
    member_id = V.as_str(V.require(data, "member_id"), "member_id")
    require_owner(caller, member_id)

    get_or_404(db.venues, venue_id, "venue")
    get_or_404(db.members, member_id, "member")

    game_card_id = data.get("game_card_id")
    if game_card_id is not None:
        get_or_404(db.game_cards, game_card_id, "game card")

    party_size = data.get("party_size", 1)
    party_size = V.int_min(party_size, "party_size", 1)

    ticket = stamp_common({
        "venue_id": venue_id,
        "member_id": member_id,
        "game_card_id": game_card_id,
        "party_size": party_size,
        "status": "WAITING",
        "assigned_bay_id": None,
    })
    db.queue_tickets[ticket["id"]] = ticket
    return success(queue_ticket_out(ticket), status=201)


@bp.get("/golf/queue-tickets/<queue_ticket_id>")
def get_queue_ticket(queue_ticket_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    t = get_or_404(db.queue_tickets, queue_ticket_id, "queue ticket")
    return success(queue_ticket_out(t))


@bp.get("/golf/queue-tickets")
def list_queue_tickets():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(request.args)
    records = list(db.queue_tickets.values())
    for key in ("venue_id", "member_id", "game_card_id", "assigned_bay_id"):
        val = request.args.get(key)
        if val is not None:
            records = [t for t in records if t.get(key) == val]
    window, total = paginate(records, limit, offset)
    return list_success([queue_ticket_out(t) for t in window], limit, offset, total)


@bp.post("/golf/queue-tickets/<queue_ticket_id>/cancel")
def cancel_queue_ticket(queue_ticket_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk"})
    t = get_or_404(db.queue_tickets, queue_ticket_id, "queue ticket")
    require_owner(caller, t["member_id"])
    V.body()
    if t["status"] != "WAITING":
        raise_err(ERR_INVALID_STATE, "ticket is not WAITING")
    t["status"] = "CANCELLED"
    touch(t)
    return success(queue_ticket_out(t))

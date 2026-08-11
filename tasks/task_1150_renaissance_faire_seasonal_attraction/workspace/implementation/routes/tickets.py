"""Ticket endpoints."""
from flask import Blueprint

from db import store, clock_now
from errors import (
    ERR_TICKET_NOT_FOUND,
    ERR_TICKET_NOT_VALID,
    ERR_DAY_NOT_OPERATING,
    conflict,
)
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import recompute_order_redemption, adjust_outstanding
from util import check_unknown, mutate, public_view, now_str

bp = Blueprint("tickets", __name__)


def load_ticket(tid):
    return load(store.tickets, tid, ERR_TICKET_NOT_FOUND, "ticket")


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.tickets),
        [("order_id", "order_id"), ("faire_day_id", "faire_day_id"), ("status", "status")],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(t) for t in page], limit, offset, total)


@bp.route("/tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    require_roles()
    return obj_response(public_view(load_ticket(tid)))


@bp.route("/tickets/<tid>/redeem", methods=["POST"])
def redeem_ticket(tid):
    require_roles("GateAgent")
    ticket = load_ticket(tid)
    check_unknown(get_body(), set())
    if ticket["status"] != "VALID":
        raise conflict(ERR_TICKET_NOT_VALID, "redeem requires a VALID ticket")
    order = store.orders[ticket["order_id"]]
    if ticket["ticket_type"] == "DAY":
        day = store.faire_days.get(ticket["faire_day_id"])
        if day is None or day["status"] != "OPERATING":
            raise conflict(ERR_DAY_NOT_OPERATING, "the ticket's faire day is not OPERATING")
    else:  # SEASON pass: some day of the season OPERATING on today's calendar date
        today = clock_now().date()
        ok = any(
            d["season_id"] == order["season_id"]
            and d["status"] == "OPERATING"
            and d["date"].date() == today
            for d in store.faire_days.values()
        )
        if not ok:
            raise conflict(
                ERR_DAY_NOT_OPERATING, "no OPERATING faire day of the season today"
            )
    mutate(ticket, status="REDEEMED", redeemed_at=now_str())
    recompute_order_redemption(order, "redeem")
    return obj_response(public_view(ticket))


@bp.route("/tickets/<tid>/void", methods=["POST"])
def void_ticket(tid):
    require_roles("GateAgent")
    ticket = load_ticket(tid)
    check_unknown(get_body(), set())
    if ticket["status"] != "VALID":
        raise conflict(ERR_TICKET_NOT_VALID, "void requires a VALID ticket")
    mutate(ticket, status="VOID")
    order = store.orders[ticket["order_id"]]
    season = store.seasons.get(order["season_id"])
    if season is not None:
        adjust_outstanding(season, -1)
    recompute_order_redemption(order, "void")
    return obj_response(public_view(ticket))

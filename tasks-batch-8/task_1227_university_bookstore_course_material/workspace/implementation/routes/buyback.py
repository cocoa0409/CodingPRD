"""Buyback tickets: dual-variant offer pricing, OCC on title version, and the
accept / pay / reject lifecycle with compensation (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, now, new_entity, touch, pub
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_OWNER,
    ERR_NOT_FOUND, ERR_STALE_VERSION, ERR_BUYBACK_WINDOW_CLOSED,
    ERR_QUOTE_EXPIRED, ERR_WHOLESALE_QUOTE_MISSING,
)
from middleware import (
    require_roles, body, get_str, get_int, get_or_404,
)
from response import success, list_response
from services import (
    NEEDS_RATIO, QUOTE_TTL_HOURS, demand_quota, accepted_count,
    active_wholesale_quote, buyback_window_open, round_half_up_cents,
)
from routes.titles import CONDITIONS

bp = Blueprint("buyback", __name__)

READ_ROLES = ("BookstoreManager", "Student")


@bp.post("/bookstore/buyback-tickets")
def create_ticket():
    uid, _ = require_roles("Student")
    student = store.students.get(uid)
    if student is None:
        raise ApiError(ERR_NOT_FOUND, 404, "student not found")
    data = body()
    title_id = get_str(data, "title_id")
    upcoming_term_id = get_str(data, "upcoming_term_id")
    # existence, left to right
    title = get_or_404(store.titles, title_id, "title")
    get_or_404(store.terms, upcoming_term_id, "term")
    # OCC (§2.7): expected_title_version pins the title version
    expected = get_int(data, "expected_title_version")
    if expected != title["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "stale title version")
    # business temporal (priority 7): an open buyback window must contain now
    if not buyback_window_open():
        raise ApiError(ERR_BUYBACK_WINDOW_CLOSED, 422,
                       "no open buyback window contains now")
    # business constraint (priority 8)
    condition = data.get("condition")
    if not isinstance(condition, str) or condition not in CONDITIONS:
        raise ApiError(ERR_VALIDATION, 400, "invalid condition")
    # calculations.buyback_offer_price: demand quota -> variant selection
    quota = demand_quota(title["id"], upcoming_term_id)
    consumed = accepted_count(title["id"], upcoming_term_id)
    if quota > 0 and consumed < quota:
        pricing_variant = "NEEDS_BASED"
        quoted = round_half_up_cents(NEEDS_RATIO * title["list_price_cents"])
    else:
        pricing_variant = "WHOLESALE"
        quote = active_wholesale_quote(title["id"], condition)
        if quote is None:
            raise ApiError(ERR_WHOLESALE_QUOTE_MISSING, 422,
                           "no active wholesale quote for (title, condition)")
        quoted = quote["price_cents"]
    ticket = new_entity()
    ticket.update({
        "student_id": uid,
        "title_id": title["id"],
        "upcoming_term_id": upcoming_term_id,
        "condition": condition,
        "pricing_variant": pricing_variant,
        "quoted_price_cents": quoted,
        "quote_valid_until": now() + timedelta(hours=QUOTE_TTL_HOURS),
        "status": "QUOTED",
    })
    store.buyback_tickets[ticket["id"]] = ticket
    # creation advances the title version (why OCC pins it)
    touch(title)
    return success(pub(ticket), status=201)


@bp.get("/bookstore/buyback-tickets")
def list_tickets():
    require_roles(*READ_ROLES)
    student_id = request.args.get("student_id")
    title_id = request.args.get("title_id")
    upcoming_term_id = request.args.get("upcoming_term_id")
    status = request.args.get("status")
    items = [
        t for t in store.buyback_tickets.values()
        if (student_id is None or t["student_id"] == student_id)
        and (title_id is None or t["title_id"] == title_id)
        and (upcoming_term_id is None or t["upcoming_term_id"] == upcoming_term_id)
        and (status is None or t["status"] == status)
    ]
    return list_response(items)


@bp.get("/bookstore/buyback-tickets/<tid>")
def get_ticket(tid):
    require_roles(*READ_ROLES)
    return success(pub(get_or_404(store.buyback_tickets, tid, "ticket")))


@bp.post("/bookstore/buyback-tickets/<tid>/accept")
def accept_ticket(tid):
    uid, _ = require_roles("Student")
    ticket = get_or_404(store.buyback_tickets, tid, "ticket")
    if ticket["student_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the ticket owner")
    if ticket["status"] != "QUOTED":
        raise ApiError(ERR_INVALID_STATE, 409, "ticket not in QUOTED")
    if now() > ticket["quote_valid_until"]:
        raise ApiError(ERR_QUOTE_EXPIRED, 422, "quote validity has passed")
    if not buyback_window_open():
        raise ApiError(ERR_BUYBACK_WINDOW_CLOSED, 422,
                       "no open buyback window contains now")
    # acceptance consumes one unit of demand quota (accepted/paid count) and
    # adds one used copy to stock
    title = store.titles[ticket["title_id"]]
    title["used_stock_qty"] += 1
    touch(title)
    ticket["status"] = "ACCEPTED"
    touch(ticket)
    return success(pub(ticket))


@bp.post("/bookstore/buyback-tickets/<tid>/pay")
def pay_ticket(tid):
    require_roles("BookstoreManager")
    ticket = get_or_404(store.buyback_tickets, tid, "ticket")
    if ticket["status"] != "ACCEPTED":
        raise ApiError(ERR_INVALID_STATE, 409, "ticket not in ACCEPTED")
    ticket["status"] = "PAID"
    touch(ticket)
    return success(pub(ticket))


@bp.post("/bookstore/buyback-tickets/<tid>/reject")
def reject_ticket(tid):
    require_roles("BookstoreManager")
    ticket = get_or_404(store.buyback_tickets, tid, "ticket")
    if ticket["status"] not in ("QUOTED", "ACCEPTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "ticket not in QUOTED or ACCEPTED")
    data = body()
    if "reason" in data and data["reason"] is not None:
        get_str(data, "reason")  # accepted, not persisted (not in schema)
    if ticket["status"] == "ACCEPTED":
        # intake condition mismatch: compensate stock and release the quota
        title = store.titles[ticket["title_id"]]
        title["used_stock_qty"] -= 1
        touch(title)
    ticket["status"] = "REJECTED"
    touch(ticket)
    return success(pub(ticket))

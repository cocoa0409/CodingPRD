"""Paddle-raise appeal gifts and multi-installment pledges."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    ALL_ROLES, ApiError, authenticate, body, clock_dt, db, fetch, get_dt,
    get_int, get_str, new_row, ok, ok_list, paged, pagination, parse_dt,
    public, q, q_enum, rows, touch,
)

bp = Blueprint("appeal", __name__)

PLEDGE_STATUSES = ("PROMISED", "PARTIALLY_FULFILLED", "FULFILLED", "LAPSED")


# ---------------------------------------------------------------- paddle raises
@bp.post("/api/paddle-raises")
def create_paddle_raise():
    authenticate(("AuctionManager", "EventOrganizer"))
    payload = body()
    event_id = get_str(payload, "event_id")
    bidder_id = get_str(payload, "bidder_id")
    level = get_int(payload, "level_cents", minimum=1)

    event = fetch("events", event_id)
    bidder = fetch("bidders", bidder_id)
    calc.gate(event, restricted=True)
    if not bidder["payment_method_on_file"]:
        raise ApiError("ERR_NO_PAYMENT_METHOD", "the guest has no stored payment method")

    remaining = max(0, event["match_cap_cents"] - event["match_awarded_cents"])
    raw_match = calc.round_half_up(level)
    match = min(raw_match, remaining)

    gift = new_row(event_id=event_id, bidder_id=bidder_id, invoice_id=None,
                   level_cents=level, match_cents=match, settlement_status="UNSETTLED")
    db.paddles[gift["id"]] = gift
    event["match_awarded_cents"] = calc.event_match_awarded(event_id)
    touch(event)
    return ok(public(gift), 201)


@bp.get("/api/paddle-raises/<pid>")
def read_paddle_raise(pid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("paddles", pid)))


@bp.get("/api/paddle-raises")
def list_paddle_raises():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    bidder_id = q("bidder_id")
    invoice_id = q("invoice_id")
    items = [g for g in rows("paddles")
             if (event_id is None or g["event_id"] == event_id)
             and (bidder_id is None or g["bidder_id"] == bidder_id)
             and (invoice_id is None or g["invoice_id"] == invoice_id)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


# ---------------------------------------------------------------- pledges
@bp.post("/api/pledges")
def create_pledge():
    authenticate(("FinanceOfficer", "EventOrganizer"))
    payload = body()
    event_id = get_str(payload, "event_id")
    bidder_id = get_str(payload, "bidder_id")
    total = get_int(payload, "total_amount_cents", minimum=1)
    installments = get_int(payload, "installment_count", minimum=1)
    due_raw, _ = get_dt(payload, "first_due_utc")

    event = fetch("events", event_id)
    fetch("bidders", bidder_id)
    calc.gate(event)
    pledge = new_row(event_id=event_id, bidder_id=bidder_id,
                     total_amount_cents=total, installment_count=installments,
                     first_due_utc=due_raw, received_amount_cents=0,
                     status="PROMISED")
    db.pledges[pledge["id"]] = pledge
    return ok(public(pledge), 201)


@bp.get("/api/pledges/<pid>")
def read_pledge(pid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("pledges", pid)))


@bp.get("/api/pledges")
def list_pledges():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    bidder_id = q("bidder_id")
    status = q_enum("status", PLEDGE_STATUSES)
    items = [p for p in rows("pledges")
             if (event_id is None or p["event_id"] == event_id)
             and (bidder_id is None or p["bidder_id"] == bidder_id)
             and (status is None or p["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/pledges/<pid>/installments")
def record_installment(pid):
    authenticate(("FinanceOfficer",))
    payload = body()
    amount = get_int(payload, "amount_cents", minimum=1)
    pledge = fetch("pledges", pid)
    calc.gate(fetch("events", pledge["event_id"]))
    if pledge["status"] in ("FULFILLED", "LAPSED"):
        raise ApiError("ERR_PLEDGE_TERMINAL", "the pledge is in a terminal state")
    total_after = pledge["received_amount_cents"] + amount
    pledge["received_amount_cents"] = total_after
    if total_after < pledge["total_amount_cents"]:
        pledge["status"] = "PARTIALLY_FULFILLED"
    else:
        pledge["status"] = "FULFILLED"
    touch(pledge)
    return ok(public(pledge))


@bp.post("/api/pledges/<pid>/lapse")
def lapse_pledge(pid):
    authenticate(("FinanceOfficer",))
    pledge = fetch("pledges", pid)
    calc.gate(fetch("events", pledge["event_id"]))
    if pledge["status"] in ("FULFILLED", "LAPSED"):
        raise ApiError("ERR_PLEDGE_TERMINAL", "the pledge is in a terminal state")
    deadline = parse_dt(pledge["first_due_utc"]) + timedelta(days=30)
    if not clock_dt() > deadline:
        raise ApiError("ERR_INVALID_STATE", "the grace window has not expired")
    pledge["status"] = "LAPSED"
    touch(pledge)
    return ok(public(pledge))

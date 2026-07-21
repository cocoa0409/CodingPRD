"""Logical clock, gala events, tables."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    ALL_ROLES, ApiError, authenticate, body, clock_dt, db, fetch, fmt_dt, get_dt,
    get_enum, get_int, get_str, new_row, ok, ok_list, paged, pagination,
    parse_dt, public, q, q_enum, rows, touch,
)

bp = Blueprint("events", __name__)

EVENT_STATUSES = ("DRAFT", "PUBLISHED", "LIVE", "SETTLING", "CLOSED")
TABLE_STATUSES = ("AVAILABLE", "SOLD_OUT")


# ---------------------------------------------------------------- clock
@bp.post("/api/_clock/set_current_utc")
def set_clock():
    authenticate(("EventOrganizer", "AuctionManager", "FinanceOfficer"))
    payload = body()
    raw, parsed = get_dt(payload, "to_iso8601")
    # PRD: timestamps render as ISO 8601 UTC with three fractional-second digits.
    db.clock = fmt_dt(parsed)
    return ok({"current_utc": db.clock})


# ---------------------------------------------------------------- events
@bp.post("/api/events")
def create_event():
    authenticate(("EventOrganizer",))
    payload = body()
    name = get_str(payload, "name")
    start_raw, _ = get_dt(payload, "event_start_utc")
    end_raw, _ = get_dt(payload, "event_end_utc")
    cap = get_int(payload, "match_cap_cents", required=False, default=0, minimum=0)
    event = new_row(
        name=name, event_start_utc=start_raw, event_end_utc=end_raw,
        match_cap_cents=cap, status="DRAFT", match_awarded_cents=0,
        gross_collected_cents=0, open_lot_count=0, unpaid_invoice_count=0,
    )
    db.events[event["id"]] = event
    return ok(calc.event_view(event), 201)


@bp.get("/api/events/<eid>")
def read_event(eid):
    authenticate(ALL_ROLES)
    return ok(calc.event_view(fetch("events", eid)))


@bp.get("/api/events")
def list_events():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = q_enum("status", EVENT_STATUSES)
    items = [e for e in rows("events") if status is None or e["status"] == status]
    total = len(items)
    window = [calc.event_view(e) for e in items[offset:offset + limit]]
    return ok_list(window, limit, offset, total)


def _lifecycle(eid, expected):
    authenticate(("EventOrganizer",))
    event = fetch("events", eid)
    if event["status"] != expected:
        raise ApiError("ERR_INVALID_STATE",
                       "event is in %s, expected %s" % (event["status"], expected))
    return event


@bp.post("/api/events/<eid>/publish")
def publish_event(eid):
    event = _lifecycle(eid, "DRAFT")
    if not any(t["event_id"] == event["id"] for t in db.tables.values()):
        raise ApiError("ERR_INVALID_STATE", "the event has no ticket tables")
    event["status"] = "PUBLISHED"
    touch(event)
    return ok(calc.event_view(event))


@bp.post("/api/events/<eid>/unpublish")
def unpublish_event(eid):
    event = _lifecycle(eid, "PUBLISHED")
    for order in db.orders.values():
        if order["event_id"] == event["id"] and order["payment_status"] in ("INVOICED", "PAID"):
            raise ApiError("ERR_TICKET_ORDERS_EXIST", "billed ticket orders exist")
    event["status"] = "DRAFT"
    table_ids = {t["id"] for t in db.tables.values() if t["event_id"] == event["id"]}
    for hold in rows("holds"):
        if hold["table_id"] in table_ids and hold["status"] == "HELD":
            hold["status"] = "RELEASED"
            touch(hold)
            table = db.tables.get(hold["table_id"])
            if table is not None:
                calc.recompute_table(table)
    touch(event)
    return ok(calc.event_view(event))


@bp.post("/api/events/<eid>/go-live")
def go_live(eid):
    event = _lifecycle(eid, "PUBLISHED")
    now = clock_dt()
    if not now < parse_dt(event["event_end_utc"]):
        raise ApiError("ERR_INVALID_STATE", "the event has already ended")
    event["status"] = "LIVE"
    for item in rows("items"):
        if item["event_id"] != event["id"] or item["listing_status"] != "DRAFT":
            continue
        if parse_dt(item["open_at_utc"]) <= now < parse_dt(item["close_at_utc"]):
            item["listing_status"] = "OPEN"
            touch(item)
    event["open_lot_count"] = calc.event_open_lots(event["id"])
    touch(event)
    return ok(calc.event_view(event))


@bp.post("/api/events/<eid>/start-settlement")
def start_settlement(eid):
    event = _lifecycle(eid, "LIVE")
    if calc.event_open_lots(event["id"]) != 0:
        raise ApiError("ERR_OPEN_LOTS_REMAIN", "lots are still open")
    event["status"] = "SETTLING"
    touch(event)
    return ok(calc.event_view(event))


@bp.post("/api/events/<eid>/close")
def close_event(eid):
    event = _lifecycle(eid, "SETTLING")
    if calc.event_unpaid_invoices(event["id"]) != 0:
        raise ApiError("ERR_OPEN_INVOICES_REMAIN", "unpaid invoices remain")
    if not any(r["event_id"] == event["id"] and r["status"] == "FINALIZED"
               for r in db.runs.values()):
        raise ApiError("ERR_NO_FINALIZED_RUN", "no finalized reconciliation run")
    event["status"] = "CLOSED"
    now = clock_dt()
    for pledge in rows("pledges"):
        if pledge["event_id"] != event["id"] or pledge["status"] != "PROMISED":
            continue
        if now > parse_dt(pledge["first_due_utc"]) + timedelta(days=30):
            pledge["status"] = "LAPSED"
            touch(pledge)
    touch(event)
    return ok(calc.event_view(event))


@bp.get("/api/events/<eid>/revenue-summary")
def revenue_summary(eid):
    authenticate(("EventOrganizer", "FinanceOfficer"))
    event = fetch("events", eid)
    return ok({
        "tickets_cents": calc.channel_tickets(eid),
        "auction_cents": calc.channel_auction(eid),
        "paddle_cents": calc.channel_paddle(eid),
        "pledge_booked_cents": calc.pledge_channel(eid, "BOOKED"),
        "pledge_cash_cents": calc.pledge_channel(eid, "CASH_BASIS"),
        "sponsorship_cents": calc.channel_sponsorship(eid),
        "gross_collected_cents": event["gross_collected_cents"],
        "match_awarded_cents": event["match_awarded_cents"],
    })


# ---------------------------------------------------------------- tables
@bp.post("/api/events/<eid>/tables")
def create_table(eid):
    authenticate(("EventOrganizer",))
    payload = body()
    name = get_str(payload, "table_name")
    seat_count = get_int(payload, "seat_count", minimum=1)
    table_price = get_int(payload, "table_price_cents", minimum=0)
    seat_price = get_int(payload, "seat_price_cents", minimum=0)
    event = fetch("events", eid)
    calc.gate(event)
    table = new_row(event_id=event["id"], table_name=name, seat_count=seat_count,
                    table_price_cents=table_price, seat_price_cents=seat_price,
                    seats_reserved=0, status="AVAILABLE")
    db.tables[table["id"]] = table
    return ok(public(table), 201)


@bp.get("/api/tables/<tid>")
def read_table(tid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("tables", tid)))


@bp.get("/api/tables")
def list_tables():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    status = q_enum("status", TABLE_STATUSES)
    items = [t for t in rows("tables")
             if (event_id is None or t["event_id"] == event_id)
             and (status is None or t["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)

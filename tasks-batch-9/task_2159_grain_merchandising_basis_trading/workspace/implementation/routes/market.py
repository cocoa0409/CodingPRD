"""Bids, the futures book and margin calls."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from aggregates import recompute_desk, sync_position
from auth import ALL_ROLES, endpoint
from calc import (INITIAL_MARGIN_USD_PER_LOT, MARGIN_CALL_CURE_HOURS,
                  margin_call_amount, mark_to_market, realized_on_close,
                  weighted_average)
from errors import fail
from response import ok, paged
from serializers import bid_out, margin_call_out, position_out
from store import (D, apply_changes, db, new_row, parse_date, r2, r4, sort_rows)
from validate import (COMMODITIES, SIDES, body, guard_payload, lookup, lookup_fk,
                      req_date, req_enum, req_int, req_month, req_num, req_ts)

bp = Blueprint("market", __name__)


# --------------------------------------------------------------------------
# Bid
# --------------------------------------------------------------------------
@bp.post("/grain/bids")
@endpoint(["Merchandiser"])
def create_bid(actor):
    payload = guard_payload(body())
    location = lookup_fk(payload, "location_id", "elevator_locations")
    if location is None:
        fail("ERR_INVALID_REQUEST")
    commodity = req_enum(payload, "commodity_code", COMMODITIES)
    futures_month = req_month(payload, "futures_month")
    period_start = req_date(payload, "delivery_period_start")
    period_end = req_date(payload, "delivery_period_end")
    if period_end < period_start:
        fail("ERR_INVALID_REQUEST",
             "delivery_period_end may not precede delivery_period_start.")
    basis_cents = req_num(payload, "basis_cents")
    max_bushels = req_int(payload, "max_bushels", minimum=0, exclusive_min=True)
    expires_at = req_ts(payload, "expires_at")

    row = new_row()
    row.update({
        "location_id": location["id"],
        "commodity_code": commodity,
        "futures_month": futures_month,
        "delivery_period_start": period_start.isoformat(),
        "delivery_period_end": period_end.isoformat(),
        "basis_cents": basis_cents,
        "max_bushels": max_bushels,
        "expires_at": expires_at,
        "contracted_bushels": Decimal("0.00"),
        "status": "DRAFT",
    })
    db.bids[row["id"]] = row
    return ok(bid_out(row), 201)


@bp.post("/grain/bids/<bid_id>/activate")
@endpoint(["Merchandiser"])
def activate_bid(actor, bid_id):
    bid = lookup("bids", bid_id)
    if bid["status"] not in ("DRAFT", "SUSPENDED"):
        fail("ERR_INVALID_STATE")
    if db.now >= bid["expires_at"]:
        fail("ERR_BID_EXPIRED")
    for other in db.bids.values():
        if other["id"] == bid["id"]:
            continue
        if other["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if (other["location_id"], other["commodity_code"], other["futures_month"],
                other["delivery_period_start"]) == (
                bid["location_id"], bid["commodity_code"], bid["futures_month"],
                bid["delivery_period_start"]):
            fail("ERR_DUPLICATE_BID")
    apply_changes(bid, {"status": "ACTIVE"})
    return ok(bid_out(bid))


@bp.post("/grain/bids/<bid_id>/suspend")
@endpoint(["Merchandiser"])
def suspend_bid(actor, bid_id):
    bid = lookup("bids", bid_id)
    if bid["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    apply_changes(bid, {"status": "SUSPENDED"})
    return ok(bid_out(bid))


@bp.post("/grain/bids/<bid_id>/withdraw")
@endpoint(["Merchandiser"])
def withdraw_bid(actor, bid_id):
    bid = lookup("bids", bid_id)
    if bid["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE")
    apply_changes(bid, {"status": "WITHDRAWN"})
    return ok(bid_out(bid))


@bp.get("/grain/bids")
@endpoint(ALL_ROLES)
def list_bids(actor):
    rows = list(db.bids.values())
    for field in ("location_id", "commodity_code", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), bid_out)


@bp.get("/grain/bids/<bid_id>")
@endpoint(ALL_ROLES)
def read_bid(actor, bid_id):
    return ok(bid_out(lookup("bids", bid_id)))


# --------------------------------------------------------------------------
# HedgePosition
# --------------------------------------------------------------------------
@bp.post("/grain/hedge-positions")
@endpoint(["FuturesTrader"])
def create_position(actor):
    payload = guard_payload(body())
    desk = lookup_fk(payload, "desk_id", "trading_desks")
    if desk is None:
        fail("ERR_INVALID_REQUEST")
    commodity = req_enum(payload, "commodity_code", COMMODITIES)
    futures_month = req_month(payload, "futures_month")
    side = req_enum(payload, "side", SIDES)
    lots_open = req_int(payload, "lots_open", minimum=0, exclusive_min=True)
    avg_entry = req_num(payload, "avg_entry_price_cents")

    row = new_row()
    row.update({
        "desk_id": desk["id"],
        "commodity_code": commodity,
        "futures_month": futures_month,
        "side": side,
        "lots_open": lots_open,
        "avg_entry_price_cents": r4(avg_entry),
        "lots_committed": 0,
        "lots_available": lots_open,
        "posted_margin_usd": r2(D(lots_open) * INITIAL_MARGIN_USD_PER_LOT[commodity]),
        "last_settlement_price_cents": r4(avg_entry),
        "unrealized_pnl_usd": Decimal("0.00"),
        "realized_pnl_usd": Decimal("0.00"),
        "status": "OPEN",
    })
    db.hedge_positions[row["id"]] = row
    recompute_desk(desk)
    return ok(position_out(row), 201)


@bp.post("/grain/hedge-positions/<position_id>/add-lots")
@endpoint(["FuturesTrader"])
def add_lots(actor, position_id):
    position = lookup("hedge_positions", position_id)
    payload = guard_payload(body())
    lots = req_int(payload, "lots", minimum=0, exclusive_min=True)
    fill_price = req_num(payload, "fill_price_cents")
    if position["status"] != "OPEN":
        fail("ERR_INVALID_STATE")

    new_avg, _total = weighted_average([
        (position["avg_entry_price_cents"], position["lots_open"]),
        (fill_price, lots),
    ])
    new_lots_open = position["lots_open"] + lots
    sync_position(position, {
        "avg_entry_price_cents": new_avg,
        "lots_open": new_lots_open,
        "posted_margin_usd": r2(
            D(new_lots_open)
            * INITIAL_MARGIN_USD_PER_LOT[position["commodity_code"]]),
    })
    recompute_desk(db.trading_desks[position["desk_id"]])
    return ok(position_out(position))


@bp.post("/grain/hedge-positions/<position_id>/mark-to-market")
@endpoint(["FuturesTrader"])
def mark_position(actor, position_id):
    position = lookup("hedge_positions", position_id)
    payload = guard_payload(body())
    price = req_num(payload, "settlement_price_cents")
    if position["status"] != "OPEN":
        fail("ERR_INVALID_STATE")

    unrealized, equity, _maintenance, breached = mark_to_market(position, price)
    changes = {
        "last_settlement_price_cents": price,
        "unrealized_pnl_usd": unrealized,
    }
    call_row = None
    if breached:
        changes["status"] = "MARGIN_CALL"
        amount = margin_call_amount(position, equity)
        call_row = new_row()
        call_row.update({
            "hedge_position_id": position["id"],
            "call_amount_usd": amount,
            "issued_at": db.now,
            "cure_deadline_at": db.now + timedelta(hours=MARGIN_CALL_CURE_HOURS),
            "cured_amount_usd": Decimal("0.00"),
            "status": "OPEN",
        })
    apply_changes(position, changes)
    if call_row is not None:
        db.margin_calls[call_row["id"]] = call_row
    recompute_desk(db.trading_desks[position["desk_id"]])
    return ok(position_out(position))


@bp.post("/grain/hedge-positions/<position_id>/liquidate")
@endpoint(["FuturesTrader"])
def liquidate_position(actor, position_id):
    position = lookup("hedge_positions", position_id)
    payload = guard_payload(body())
    price = req_num(payload, "settlement_price_cents")

    open_call = None
    if position["status"] == "OPEN":
        if position["lots_committed"] != 0:
            fail("ERR_INVALID_STATE")
    elif position["status"] == "MARGIN_CALL":
        for call in sort_rows(db.margin_calls.values()):
            if call["hedge_position_id"] == position["id"] \
                    and call["status"] == "OPEN":
                open_call = call
                break
        if open_call is None or not (open_call["cure_deadline_at"] < db.now):
            fail("ERR_INVALID_STATE")
    else:
        fail("ERR_INVALID_STATE")

    if open_call is not None:
        apply_changes(open_call, {"status": "DEFAULTED"})

    realized = D(position["realized_pnl_usd"]) + realized_on_close(
        position, price, position["lots_open"])
    apply_changes(position, {
        "realized_pnl_usd": r2(realized),
        "posted_margin_usd": Decimal("0.00"),
        "unrealized_pnl_usd": Decimal("0.00"),
        "status": "LIQUIDATED",
    })
    recompute_desk(db.trading_desks[position["desk_id"]])
    return ok(position_out(position))


@bp.get("/grain/hedge-positions")
@endpoint(ALL_ROLES)
def list_positions(actor):
    rows = list(db.hedge_positions.values())
    for field in ("desk_id", "commodity_code", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), position_out)


@bp.get("/grain/hedge-positions/<position_id>")
@endpoint(ALL_ROLES)
def read_position(actor, position_id):
    return ok(position_out(lookup("hedge_positions", position_id)))


# --------------------------------------------------------------------------
# MarginCall
# --------------------------------------------------------------------------
@bp.post("/grain/margin-calls/<margin_call_id>/cure")
@endpoint(["RiskOfficer"])
def cure_margin_call(actor, margin_call_id):
    call = lookup("margin_calls", margin_call_id)
    payload = guard_payload(body())
    payment = req_num(payload, "payment_usd")
    if call["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    if db.now > call["cure_deadline_at"]:
        fail("ERR_MARGIN_CALL_EXPIRED")
    if D(payment) < D(call["call_amount_usd"]):
        fail("ERR_CURE_AMOUNT_INSUFFICIENT")

    apply_changes(call, {"status": "CURED", "cured_amount_usd": r2(payment)})
    position = db.hedge_positions.get(call["hedge_position_id"])
    if position is not None:
        apply_changes(position, {
            "posted_margin_usd": r2(D(position["posted_margin_usd"]) + D(payment)),
            "status": "OPEN",
        })
        recompute_desk(db.trading_desks[position["desk_id"]])
    return ok(margin_call_out(call))


@bp.get("/grain/margin-calls")
@endpoint(ALL_ROLES)
def list_margin_calls(actor):
    rows = list(db.margin_calls.values())
    for field in ("hedge_position_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), margin_call_out)


@bp.get("/grain/margin-calls/<margin_call_id>")
@endpoint(ALL_ROLES)
def read_margin_call(actor, margin_call_id):
    return ok(margin_call_out(lookup("margin_calls", margin_call_id)))

"""Auction lots, bids and the two valuation variants."""
from flask import Blueprint

import calc
import ledger
from core import (
    ALL_ROLES, ApiError, authenticate, body, clock_dt, db, fetch, get_dt,
    get_enum, get_int, get_str, new_row, ok, ok_list, own_check, paged,
    pagination, parse_dt, public, q, q_enum, rows, touch,
)

bp = Blueprint("auction", __name__)

LISTING_STATUSES = ("DRAFT", "OPEN", "AWARDED", "PASSED")
SETTLEMENT_STATUSES = ("UNSETTLED", "INVOICED", "PAID")
BID_STATUSES = ("ACTIVE", "WON", "LOST", "RETRACTED")
ITEM_TYPES = ("SILENT", "LIVE")
VARIANTS = ("PROXY_SETTLED", "PLACED_AMOUNT")


@bp.post("/api/auction-items")
def create_item():
    authenticate(("AuctionManager",))
    payload = body()
    event_id = get_str(payload, "event_id")
    title = get_str(payload, "title")
    item_type = get_enum(payload, "item_type", ITEM_TYPES)
    starting = get_int(payload, "starting_bid_cents", minimum=0)
    increment = get_int(payload, "min_increment_cents", minimum=1)
    fmv = get_int(payload, "estimated_fmv_cents", minimum=0)
    open_raw, open_at = get_dt(payload, "open_at_utc")
    close_raw, close_at = get_dt(payload, "close_at_utc")
    if not close_at > open_at:
        raise ApiError("ERR_INVALID_REQUEST", "close_at_utc must be after open_at_utc")
    sequence = get_int(payload, "live_lot_sequence", required=False, default=None)

    event = fetch("events", event_id)
    calc.gate(event, restricted=True)
    item = new_row(event_id=event_id, title=title, item_type=item_type,
                   starting_bid_cents=starting, min_increment_cents=increment,
                   estimated_fmv_cents=fmv, open_at_utc=open_raw,
                   close_at_utc=close_raw, live_lot_sequence=sequence,
                   listing_status="DRAFT", settlement_status="UNSETTLED",
                   current_leading_amount_cents=0, winning_bid_id=None,
                   hammer_price_cents=None, invoice_id=None)
    db.items[item["id"]] = item
    return ok(public(item), 201)


@bp.get("/api/auction-items/<iid>")
def read_item(iid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("items", iid)))


@bp.get("/api/auction-items")
def list_items():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    listing = q_enum("listing_status", LISTING_STATUSES)
    settlement = q_enum("settlement_status", SETTLEMENT_STATUSES)
    winning = q("winning_bid_id")
    invoice_id = q("invoice_id")
    items = [i for i in rows("items")
             if (event_id is None or i["event_id"] == event_id)
             and (listing is None or i["listing_status"] == listing)
             and (settlement is None or i["settlement_status"] == settlement)
             and (winning is None or i["winning_bid_id"] == winning)
             and (invoice_id is None or i["invoice_id"] == invoice_id)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/auction-items/<iid>/open")
def open_item(iid):
    authenticate(("AuctionManager",))
    item = fetch("items", iid)
    event = fetch("events", item["event_id"])
    calc.gate(event, restricted=True)
    if item["listing_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "lot is not DRAFT")
    if event["status"] not in ("PUBLISHED", "LIVE"):
        raise ApiError("ERR_INVALID_STATE", "the event is not open for bidding")
    now = clock_dt()
    open_at = parse_dt(item["open_at_utc"])
    close_at = parse_dt(item["close_at_utc"])
    if not (open_at <= now < close_at):
        raise ApiError("ERR_LOT_WINDOW_CLOSED", "the lot's bidding window is not current")
    if item["live_lot_sequence"] is not None:
        for other in db.items.values():
            if other["id"] == item["id"] or other["event_id"] != item["event_id"]:
                continue
            if other["listing_status"] != "OPEN":
                continue
            if other["live_lot_sequence"] != item["live_lot_sequence"]:
                continue
            o_open = parse_dt(other["open_at_utc"])
            o_close = parse_dt(other["close_at_utc"])
            if open_at < o_close and o_open < close_at:
                raise ApiError("ERR_LOT_WINDOW_CONFLICT",
                               "another open lot occupies this stage slot")
    item["listing_status"] = "OPEN"
    touch(item)
    event["open_lot_count"] = calc.event_open_lots(event["id"])
    touch(event)
    return ok(public(item))


@bp.post("/api/auction-items/<iid>/close")
def close_item(iid):
    authenticate(("AuctionManager",))
    item = fetch("items", iid)
    event = fetch("events", item["event_id"])
    calc.gate(event)
    if item["listing_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "lot is not OPEN")

    active = calc.active_bids(item["id"])
    if active:
        priced = calc.valuation(item, "PROXY_SETTLED")
        winner = active[0]
        item["listing_status"] = "AWARDED"
        item["hammer_price_cents"] = priced["amount_cents"]
        item["winning_bid_id"] = winner["id"]
        item["settlement_status"] = "INVOICED"
        for bid in active:
            bid["status"] = "WON" if bid["id"] == winner["id"] else "LOST"
            touch(bid)
        invoice = ledger.find_or_create_open_invoice(event["id"], winner["bidder_id"])
        item["invoice_id"] = invoice["id"]
        calc.append_line(invoice, "AUCTION_ITEM", item["id"], item["hammer_price_cents"])
        calc.recompute_invoice(invoice)
        ledger.bump_bidder(invoice["bidder_id"])
    else:
        item["listing_status"] = "PASSED"
    touch(item)
    event["open_lot_count"] = calc.event_open_lots(event["id"])
    touch(event)
    return ok(public(item))


@bp.get("/api/auction-items/<iid>/valuation")
def item_valuation(iid):
    authenticate(("AuctionManager", "FinanceOfficer", "EventOrganizer"))
    variant = q("variant")
    if variant is None:
        raise ApiError("ERR_INVALID_REQUEST", "field 'variant' is required")
    if variant not in VARIANTS:
        raise ApiError("ERR_INVALID_REQUEST", "field 'variant' must be one of %s"
                       % ", ".join(VARIANTS))
    item = fetch("items", iid)
    result = calc.valuation(item, variant)
    result["variant"] = variant
    return ok({"variant": variant, "amount_cents": result["amount_cents"],
               "active_bid_count": result["active_bid_count"],
               "source_bid_id": result["source_bid_id"]})


# ---------------------------------------------------------------- bids
@bp.post("/api/auction-items/<iid>/bids")
def place_bid(iid):
    uid, role = authenticate(("Bidder", "AuctionManager"))
    payload = body()
    bidder_id = get_str(payload, "bidder_id")
    amount = get_int(payload, "amount_cents", minimum=1)
    proxy = get_int(payload, "proxy_max_cents", required=False, default=0, minimum=0)

    item = fetch("items", iid)
    bidder = fetch("bidders", bidder_id)
    if role == "Bidder":
        own_check(bidder_id == uid)
    event = fetch("events", item["event_id"])
    calc.gate(event, restricted=True)

    now = clock_dt()
    if item["listing_status"] != "OPEN" or not (
            parse_dt(item["open_at_utc"]) <= now < parse_dt(item["close_at_utc"])):
        raise ApiError("ERR_ITEM_NOT_OPEN", "the lot is not open for bidding")

    if not calc.active_bids(item["id"]):
        floor = item["starting_bid_cents"]
    else:
        floor = item["current_leading_amount_cents"] + item["min_increment_cents"]
    if amount < floor:
        raise ApiError("ERR_BID_TOO_LOW", "bid is below the increment floor")

    if not bidder["payment_method_on_file"]:
        raise ApiError("ERR_NO_PAYMENT_METHOD", "the guest has no stored payment method")

    bid = new_row(item_id=item["id"], bidder_id=bidder_id, amount_cents=amount,
                  proxy_max_cents=proxy, effective_max_cents=max(amount, proxy),
                  status="ACTIVE")
    db.bids[bid["id"]] = bid
    calc.recompute_leading(item)
    touch(item)
    return ok(public(bid), 201)


@bp.get("/api/bids/<bid_id>")
def read_bid(bid_id):
    authenticate(ALL_ROLES)
    return ok(public(fetch("bids", bid_id)))


@bp.get("/api/bids")
def list_bids():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    item_id = q("item_id")
    bidder_id = q("bidder_id")
    status = q_enum("status", BID_STATUSES)
    items = [b for b in rows("bids")
             if (item_id is None or b["item_id"] == item_id)
             and (bidder_id is None or b["bidder_id"] == bidder_id)
             and (status is None or b["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/bids/<bid_id>/retract")
def retract_bid(bid_id):
    authenticate(("AuctionManager",))
    bid = fetch("bids", bid_id)
    item = db.items.get(bid["item_id"])
    if item is not None:
        calc.gate(fetch("events", item["event_id"]))
    if bid["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "bid is not ACTIVE")
    if item is None or item["listing_status"] != "OPEN":
        raise ApiError("ERR_ITEM_NOT_OPEN", "the lot is not open")
    bid["status"] = "RETRACTED"
    touch(bid)
    calc.recompute_leading(item)
    touch(item)
    return ok(public(bid))

"""The auction calendar: events, lots, opening and rescheduling (PRD §3.3)."""

from flask import Blueprint

import calc
import db
import serial
import services
import validate as v
from auth import authenticate
from db import ordered, store, touch
from errors import ApiError
from helpers import body_fk, find
from routes.listings import county_code
from util import ok, ok_list

bp = Blueprint("events", __name__)


@bp.post("/auction-events")
def create_event():
    authenticate(("AuctionOps",))
    data = v.body()
    sale = body_fk(data, "trustee_sale_id", store.trustee_sales, "ERR_TRUSTEE_SALE_NOT_FOUND")
    title = v.req_str(data, "title")
    county = county_code(data, "county_code")
    starts_at = v.req_dt(data, "starts_at")
    ends_at = v.req_dt(data, "ends_at")
    if ends_at <= starts_at:
        v.bad("Field 'ends_at' must be strictly after 'starts_at'.")
    if services.county_slot_conflict(county, starts_at, ends_at):
        raise ApiError("ERR_COUNTY_SLOT_CONFLICT")

    rec = db.new_record(
        title=title,
        county_code=county,
        trustee_sale_id=sale["id"] if sale is not None else None,
        starts_at=starts_at,
        ends_at=ends_at,
        event_status="SCHEDULED",
        reschedule_count=0,
        opened_at=None,
        lot_count=0,
    )
    store.auction_events[rec["id"]] = rec
    return ok(serial.dump("auction_event", rec), 201)


@bp.post("/auction-events/<rec_id>/lots")
def create_lot(rec_id):
    authenticate(("AuctionOps",))
    data = v.body()
    asset = body_fk(data, "asset_listing_id", store.asset_listings,
                    "ERR_ASSET_LISTING_NOT_FOUND")
    event = find(store.auction_events, rec_id, "ERR_AUCTION_EVENT_NOT_FOUND")

    lot_number = v.req_int(data, "lot_number", minimum=1)
    window_start = v.req_dt(data, "lot_window_start_at")
    window_end = v.req_dt(data, "lot_window_end_at")
    if window_end <= window_start:
        v.bad("Field 'lot_window_end_at' must be strictly after 'lot_window_start_at'.")
    opening_bid = v.req_int(data, "opening_bid_cents", minimum=1)
    reserve = v.req_int(data, "reserve_price_cents", minimum=1)
    expected_version = v.req_int(data, "expected_auction_event_version")
    min_increment = v.opt_int(data, "min_increment_cents", default=500000, minimum=1)
    if asset is None:
        v.bad("Field 'asset_listing_id' is required.")

    for other in store.auction_lots.values():
        if other["auction_event_id"] == event["id"] and other["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_LOT_NUMBER")
    if asset["listing_status"] not in ("DISCLOSURE_READY", "LISTED"):
        raise ApiError("ERR_LISTING_NOT_LISTABLE")
    if event["event_status"] != "SCHEDULED":
        raise ApiError("ERR_EVENT_NOT_SCHEDULED")
    if expected_version != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION")
    if asset["title_clearance_status"] == "DEFECTIVE":
        raise ApiError("ERR_TITLE_DEFECTIVE")
    if services.lot_window_conflict(asset["id"], window_start, window_end):
        raise ApiError("ERR_LOT_WINDOW_CONFLICT")
    if window_start < event["starts_at"] or window_end > event["ends_at"]:
        raise ApiError("ERR_LOT_WINDOW_OUTSIDE_EVENT")
    if reserve < opening_bid:
        raise ApiError("ERR_RESERVE_BELOW_OPENING")

    lot = db.new_record(
        auction_event_id=event["id"],
        asset_listing_id=asset["id"],
        lot_number=lot_number,
        lot_window_start_at=window_start,
        lot_window_end_at=window_end,
        opening_bid_cents=opening_bid,
        min_increment_cents=min_increment,
        reserve_price_cents=reserve,
        required_deposit_cents=calc.required_deposit(opening_bid, asset["occupancy_status"]),
        bid_close_at=window_end,
        extension_count=0,
        current_high_bid_cents=0,
        hammer_price_cents=0,
        provisional_buyer_premium_cents=0,
        lot_status="PENDING",
        closed_by_user_id=None,
        closed_at=None,
    )
    store.auction_lots[lot["id"]] = lot

    if asset["listing_status"] == "DISCLOSURE_READY":
        asset["listing_status"] = "LISTED"
        touch(asset)
    if services.recompute_lot_count(event):
        touch(event)
    return ok(serial.dump("auction_lot", lot), 201)


@bp.post("/auction-events/<rec_id>/open")
def open_event(rec_id):
    user_id, _role = authenticate(("AuctionOps",))
    event = find(store.auction_events, rec_id, "ERR_AUCTION_EVENT_NOT_FOUND")
    v.body()
    if event["event_status"] != "SCHEDULED":
        raise ApiError("ERR_EVENT_NOT_SCHEDULED")
    if event["lot_count"] < 1:
        raise ApiError("ERR_EVENT_HAS_NO_LOTS")
    if event["trustee_sale_id"] is not None:
        sale = store.trustee_sales.get(event["trustee_sale_id"])
        if sale is None or sale["status"] != "CONFIRMED":
            raise ApiError("ERR_TRUSTEE_SALE_NOT_CONFIRMED")
    if db.now() < event["starts_at"]:
        raise ApiError("ERR_EVENT_NOT_STARTED")

    event["event_status"] = "LIVE"
    event["opened_at"] = db.now()
    touch(event)
    for lot in services.lots_of_event(event["id"]):
        if lot["lot_status"] in ("PENDING", "SUSPENDED"):
            lot["lot_status"] = "OPEN"
            touch(lot)
    return ok(serial.dump("auction_event", event))


@bp.post("/auction-events/<rec_id>/reschedule")
def reschedule_event(rec_id):
    authenticate(("AuctionOps",))
    event = find(store.auction_events, rec_id, "ERR_AUCTION_EVENT_NOT_FOUND")
    data = v.body()
    new_starts_at = v.req_dt(data, "new_starts_at")
    new_ends_at = v.req_dt(data, "new_ends_at")
    if new_ends_at <= new_starts_at:
        v.bad("Field 'new_ends_at' must be strictly after 'new_starts_at'.")
    if new_starts_at <= db.now():
        v.bad("Field 'new_starts_at' must be strictly after the logical clock.")
    if event["event_status"] != "POSTPONED":
        raise ApiError("ERR_EVENT_NOT_POSTPONED")
    if services.county_slot_conflict(event["county_code"], new_starts_at, new_ends_at,
                                     exclude_event_id=event["id"]):
        raise ApiError("ERR_COUNTY_SLOT_CONFLICT")

    offset = new_starts_at - event["starts_at"]
    travelling = [lot for lot in services.lots_of_event(event["id"])
                  if lot["lot_status"] in ("PENDING", "SUSPENDED")]
    overrides = {}
    for lot in travelling:
        overrides[lot["id"]] = (lot["lot_window_start_at"] + offset,
                                lot["lot_window_end_at"] + offset)
    for lot in travelling:
        start_at, end_at = overrides[lot["id"]]
        if services.lot_window_conflict(lot["asset_listing_id"], start_at, end_at,
                                        exclude_lot_id=lot["id"], overrides=overrides):
            raise ApiError("ERR_LOT_WINDOW_CONFLICT")

    event["starts_at"] = new_starts_at
    event["ends_at"] = new_ends_at
    event["event_status"] = "SCHEDULED"
    event["reschedule_count"] = event["reschedule_count"] + 1
    touch(event)
    for lot in travelling:
        start_at, end_at = overrides[lot["id"]]
        lot["lot_window_start_at"] = start_at
        lot["lot_window_end_at"] = end_at
        lot["bid_close_at"] = end_at
        lot["extension_count"] = 0
        touch(lot)
    return ok(serial.dump("auction_event", event))


@bp.get("/auction-events/<rec_id>")
def get_event(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee", "Seller", "Bidder", "Anonymous"))
    event = find(store.auction_events, rec_id, "ERR_AUCTION_EVENT_NOT_FOUND")
    return ok(serial.dump("auction_event", event))


@bp.get("/auction-events")
def list_events():
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee", "Bidder", "Anonymous"))
    limit, offset = v.pagination()
    county = v.query_str("county_code")
    status = v.query_enum("event_status", calc.EVENT_STATUS)
    items = ordered(store.auction_events.values())
    if county is not None:
        items = [e for e in items if e["county_code"] == county]
    if status is not None:
        items = [e for e in items if e["event_status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("auction_event", v.page(items, limit, offset)),
                   limit, offset, total)

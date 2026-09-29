"""The county-sale leg: notice, confirmation, postponement, cancellation (PRD §3.2)."""

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

bp = Blueprint("trustee", __name__)


@bp.post("/trustee-sales")
def create_sale():
    authenticate(("Trustee",))
    data = v.body()
    asset = body_fk(data, "asset_listing_id", store.asset_listings,
                    "ERR_ASSET_LISTING_NOT_FOUND")
    county = county_code(data, "county_code")
    scheduled_at = v.req_dt(data, "sale_scheduled_at")
    max_postponements = v.opt_int(data, "statutory_max_postponements", default=3,
                                  minimum=0, maximum=10)
    if asset is None:
        v.bad("Field 'asset_listing_id' is required.")
    if county != asset["county_code"]:
        raise ApiError("ERR_COUNTY_MISMATCH")
    if scheduled_at <= db.now():
        raise ApiError("ERR_SALE_DATE_NOT_FUTURE")

    rec = db.new_record(
        asset_listing_id=asset["id"],
        county_code=county,
        sale_scheduled_at=scheduled_at,
        statutory_max_postponements=max_postponements,
        postponement_count=0,
        status="PENDING",
        confirmation_reference=None,
        cancellation_reason=None,
    )
    store.trustee_sales[rec["id"]] = rec
    return ok(serial.dump("trustee_sale", rec), 201)


@bp.post("/trustee-sales/<rec_id>/confirm")
def confirm_sale(rec_id):
    authenticate(("Trustee",))
    sale = find(store.trustee_sales, rec_id, "ERR_TRUSTEE_SALE_NOT_FOUND")
    data = v.body()
    reference = v.req_str(data, "confirmation_reference")
    if sale["status"] not in ("PENDING", "POSTPONED"):
        raise ApiError("ERR_TRUSTEE_SALE_NOT_ACTIONABLE")
    if sale["sale_scheduled_at"] <= db.now():
        raise ApiError("ERR_SALE_DATE_NOT_FUTURE")

    sale["status"] = "CONFIRMED"
    sale["confirmation_reference"] = reference
    touch(sale)
    return ok(serial.dump("trustee_sale", sale))


@bp.post("/trustee-sales/<rec_id>/postpone")
def postpone_sale(rec_id):
    authenticate(("Trustee",))
    sale = find(store.trustee_sales, rec_id, "ERR_TRUSTEE_SALE_NOT_FOUND")
    data = v.body()
    new_sale_at = v.req_dt(data, "new_sale_at")
    v.req_str(data, "postponement_reason")
    if sale["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_TRUSTEE_SALE_NOT_ACTIONABLE")
    if new_sale_at <= db.now():
        raise ApiError("ERR_SALE_DATE_NOT_FUTURE")
    if sale["postponement_count"] + 1 > sale["statutory_max_postponements"]:
        raise ApiError("ERR_POSTPONEMENT_LIMIT_EXCEEDED")

    sale["status"] = "POSTPONED"
    sale["sale_scheduled_at"] = new_sale_at
    sale["postponement_count"] = sale["postponement_count"] + 1
    touch(sale)
    services.cascade_postponement(sale)
    return ok(serial.dump("trustee_sale", sale))


@bp.post("/trustee-sales/<rec_id>/cancel")
def cancel_sale(rec_id):
    authenticate(("Trustee",))
    sale = find(store.trustee_sales, rec_id, "ERR_TRUSTEE_SALE_NOT_FOUND")
    data = v.body()
    reason = v.req_str(data, "cancellation_reason")
    if sale["status"] not in ("PENDING", "CONFIRMED", "POSTPONED"):
        raise ApiError("ERR_TRUSTEE_SALE_NOT_ACTIONABLE")

    sale["status"] = "CANCELLED"
    sale["cancellation_reason"] = reason
    touch(sale)
    services.cascade_cancellation(sale)
    return ok(serial.dump("trustee_sale", sale))


@bp.get("/trustee-sales/<rec_id>")
def get_sale(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee", "Seller"))
    sale = find(store.trustee_sales, rec_id, "ERR_TRUSTEE_SALE_NOT_FOUND")
    return ok(serial.dump("trustee_sale", sale))


@bp.get("/trustee-sales/<rec_id>/auction-events")
def list_sale_events(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee"))
    find(store.trustee_sales, rec_id, "ERR_TRUSTEE_SALE_NOT_FOUND")
    limit, offset = v.pagination()
    status = v.query_enum("event_status", calc.EVENT_STATUS)
    items = [e for e in ordered(store.auction_events.values())
             if e["trustee_sale_id"] == rec_id]
    if status is not None:
        items = [e for e in items if e["event_status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("auction_event", v.page(items, limit, offset)),
                   limit, offset, total)

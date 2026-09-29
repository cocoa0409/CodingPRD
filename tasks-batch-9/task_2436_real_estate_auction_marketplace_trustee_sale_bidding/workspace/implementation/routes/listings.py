"""Asset intake, the two disclosure axes, title work and relisting (PRD §3.1)."""

from flask import Blueprint

import calc
import db
import serial
import services
import validate as v
from auth import authenticate, require_owner
from db import ordered, store, touch
from errors import ApiError
from helpers import body_fk, find
from util import ok, ok_list

bp = Blueprint("listings", __name__)


def county_code(data, key):
    value = v.req_str(data, key, min_len=3, max_len=32)
    if value != value.upper():
        v.bad("Field '%s' must be uppercase." % key)
    return value


def state_code(data, key):
    value = v.req_str(data, key)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        v.bad("Field '%s' must be exactly two uppercase letters." % key)
    return value


@bp.post("/asset-listings")
def create_listing():
    user_id, _role = authenticate(("Seller",))
    data = v.body()
    seller = body_fk(data, "seller_id", store.sellers, "ERR_SELLER_NOT_FOUND")
    if seller is not None:
        require_owner(user_id, seller["id"])
    street = v.req_str(data, "street_address")
    city = v.req_str(data, "city")
    county = county_code(data, "county_code")
    state = state_code(data, "state_code")
    estimated = v.req_int(data, "estimated_value_cents", minimum=1)
    if seller is None:
        v.bad("Field 'seller_id' is required.")

    rec = db.new_record(
        seller_id=seller["id"],
        street_address=street,
        city=city,
        county_code=county,
        state_code=state,
        estimated_value_cents=estimated,
        occupancy_status="UNKNOWN",
        title_condition="UNKNOWN",
        eviction_risk_tier=calc.eviction_risk_tier("UNKNOWN", "UNKNOWN"),
        listing_status="INTAKE",
        title_clearance_status="PENDING",
        relist_count=0,
        second_chance_eligible=False,
        disclosure_ack_at=None,
    )
    store.asset_listings[rec["id"]] = rec
    return ok(serial.dump("asset_listing", rec), 201)


@bp.post("/asset-listings/<rec_id>/disclosures")
def file_disclosures(rec_id):
    user_id, _role = authenticate(("Seller",))
    asset = find(store.asset_listings, rec_id, "ERR_ASSET_LISTING_NOT_FOUND")
    require_owner(user_id, asset["seller_id"])
    data = v.body()
    occupancy = v.req_enum(data, "occupancy_status", calc.OCCUPANCY)
    title_condition = v.req_enum(data, "title_condition", calc.TITLE_CONDITION)
    if asset["listing_status"] != "INTAKE":
        raise ApiError("ERR_LISTING_NOT_IN_INTAKE")

    asset["occupancy_status"] = occupancy
    asset["title_condition"] = title_condition
    asset["disclosure_ack_at"] = db.now()
    asset["eviction_risk_tier"] = calc.eviction_risk_tier(occupancy, title_condition)
    asset["listing_status"] = "DISCLOSURE_READY"
    touch(asset)
    return ok(serial.dump("asset_listing", asset))


@bp.post("/asset-listings/<rec_id>/title-clearance")
def record_title_clearance(rec_id):
    authenticate(("TitleOfficer",))
    asset = find(store.asset_listings, rec_id, "ERR_ASSET_LISTING_NOT_FOUND")
    data = v.body()
    outcome = v.req_enum(data, "clearance_outcome", calc.CLEARANCE_OUTCOMES)
    verified = v.req_enum(data, "verified_title_condition", calc.TITLE_CONDITION)
    v.req_str(data, "title_report_reference")
    if asset["title_clearance_status"] != "PENDING":
        raise ApiError("ERR_TITLE_CLEARANCE_ALREADY_SET")

    asset["title_clearance_status"] = outcome
    asset["title_condition"] = verified
    asset["eviction_risk_tier"] = calc.eviction_risk_tier(asset["occupancy_status"], verified)
    touch(asset)

    # The bidder-facing projection tracks the verified finding on live lots.
    for lot in services.lots_of_asset(asset["id"]):
        if lot["lot_status"] in calc.LOT_TERMINAL:
            continue
        if services.recompute_provisional_premium(lot):
            touch(lot)
    return ok(serial.dump("asset_listing", asset))


@bp.post("/asset-listings/<rec_id>/relist")
def relist(rec_id):
    user_id, _role = authenticate(("Seller",))
    asset = find(store.asset_listings, rec_id, "ERR_ASSET_LISTING_NOT_FOUND")
    require_owner(user_id, asset["seller_id"])
    v.body()
    if asset["listing_status"] not in ("UNSOLD", "RELIST_PENDING"):
        raise ApiError("ERR_LISTING_NOT_RELISTABLE")
    if asset["title_clearance_status"] == "DEFECTIVE":
        raise ApiError("ERR_TITLE_DEFECTIVE")

    asset["listing_status"] = "DISCLOSURE_READY"
    asset["title_clearance_status"] = "PENDING"
    asset["relist_count"] = asset["relist_count"] + 1
    asset["second_chance_eligible"] = False
    touch(asset)
    return ok(serial.dump("asset_listing", asset))


@bp.get("/asset-listings/<rec_id>")
def get_listing(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Seller", "TitleOfficer", "Trustee",
                  "Bidder", "Anonymous"))
    asset = find(store.asset_listings, rec_id, "ERR_ASSET_LISTING_NOT_FOUND")
    return ok(serial.dump("asset_listing", asset))


@bp.get("/asset-listings")
def list_listings():
    authenticate(("PlatformAdmin", "AuctionOps", "Seller"))
    limit, offset = v.pagination()
    seller_id = v.query_str("seller_id")
    status = v.query_enum("listing_status", calc.LISTING_STATUS)
    county = v.query_str("county_code")
    items = ordered(store.asset_listings.values())
    if seller_id is not None:
        items = [a for a in items if a["seller_id"] == seller_id]
    if status is not None:
        items = [a for a in items if a["listing_status"] == status]
    if county is not None:
        items = [a for a in items if a["county_code"] == county]
    total = len(items)
    return ok_list(serial.dump_many("asset_listing", v.page(items, limit, offset)),
                   limit, offset, total)


@bp.get("/asset-listings/<rec_id>/trustee-sales")
def list_listing_sales(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee", "Seller"))
    find(store.asset_listings, rec_id, "ERR_ASSET_LISTING_NOT_FOUND")
    limit, offset = v.pagination()
    status = v.query_enum("status", calc.TRUSTEE_SALE_STATUS)
    items = [s for s in ordered(store.trustee_sales.values())
             if s["asset_listing_id"] == rec_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("trustee_sale", v.page(items, limit, offset)),
                   limit, offset, total)

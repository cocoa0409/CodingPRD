"""Listings and the NAP sync loop."""

from flask import Blueprint

import store
import validation as v
from auth import endpoint, resolve_listing, resolve_location
from envelope import created, ok, paginate
from errors import err
from services import add_alert, assert_not_frozen, recompute_location, touch

bp = Blueprint("listings", __name__)

MAX_SYNC_FAILURES = 3


@bp.post("/reputation/locations/<location_id>/listings")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def create_listing(location_id):
    loc = resolve_location(location_id)
    data = v.body()
    site = v.req_enum(data, "site", v.SITES)
    external_listing_id = v.req_str(data, "external_listing_id")
    listed_name = v.req_str(data, "listed_nap_name")
    listed_address = v.req_str(data, "listed_nap_address")
    listed_phone = v.req_str(data, "listed_nap_phone")

    assert_not_frozen(loc)

    for li in store.listings.values():
        if li["location_id"] == location_id and li["site"] == site:
            raise err("ERR_DUPLICATE_LISTING")

    rec = store.base_record()
    rec.update({
        "location_id": location_id,
        "site": site,
        "external_listing_id": external_listing_id,
        "listed_nap_name": listed_name,
        "listed_nap_address": listed_address,
        "listed_nap_phone": listed_phone,
        "sync_state": "PENDING_SYNC",
        "sync_failure_count": 0,
        "last_synced_at": None,
    })
    store.listings[rec["id"]] = rec

    recompute_location(loc)
    return created(store.listing_out(rec))


@bp.get("/reputation/locations/<location_id>/listings")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def list_listings(location_id):
    resolve_location(location_id)
    rows = [li for li in store.listings.values() if li["location_id"] == location_id]
    return paginate(store.by_created(rows), store.listing_out)


@bp.post("/reputation/listings/<listing_id>/sync")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def sync_listing(listing_id):
    listing, loc = resolve_listing(listing_id)
    data = v.body()
    outcome = v.req_enum(data, "outcome", v.SYNC_OUTCOMES)

    assert_not_frozen(loc)

    state = listing["sync_state"]
    # Legal source states: PENDING_SYNC, or SYNC_FAILED still below the ceiling.
    if state in ("DISCONNECTED", "CONNECTED"):
        raise err("ERR_INVALID_STATE")
    if state == "SYNC_FAILED" and listing["sync_failure_count"] >= MAX_SYNC_FAILURES:
        raise err("ERR_INVALID_STATE")

    if outcome == "SUCCESS":
        listing["listed_nap_name"] = loc["nap_name"]
        listing["listed_nap_address"] = loc["nap_address"]
        listing["listed_nap_phone"] = loc["nap_phone"]
        listing["sync_state"] = "CONNECTED"
        listing["sync_failure_count"] = 0
        listing["last_synced_at"] = store.now()
    else:
        listing["sync_failure_count"] += 1
        if listing["sync_failure_count"] >= MAX_SYNC_FAILURES:
            listing["sync_state"] = "DISCONNECTED"
        else:
            listing["sync_state"] = "SYNC_FAILED"
        add_alert(loc["id"], "LISTING_SYNC_FAILED",
                  "listing sync failed (%d consecutive)" % listing["sync_failure_count"],
                  listing["id"])

    touch(listing)
    recompute_location(loc)
    return ok(store.listing_out(listing))

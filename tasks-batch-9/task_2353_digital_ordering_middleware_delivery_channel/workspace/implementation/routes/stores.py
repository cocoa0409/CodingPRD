"""Store registration, operating hours, publishing, throttle and quotes."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
import validation
from errors import fail
from routes import common
from services import constants as K
from services import domain, serializers

bp = Blueprint("stores", __name__)

M = middleware


# ---------------------------------------------------------------- stores ----
@bp.post("/stores")
@M.endpoint(M.PLATFORM_ADMIN)
def create_store():
    payload = validation.body()
    brand_code = validation.req_str(payload, "brand_code")
    name = validation.req_str(payload, "name")
    tz = validation.req_int(payload, "timezone_offset_minutes", -720, 840)
    base_prep = validation.req_int(payload, "base_prep_minutes", 1, 60)
    capacity = validation.req_int(payload, "prep_capacity_per_bucket", 1)
    retry_limit = validation.req_int(payload, "pos_retry_limit", 1, 5)
    backlog = validation.req_int(payload, "tablet_backlog_threshold", 1)

    store = db.record()
    store.update({
        "brand_code": brand_code,
        "name": name,
        "timezone_offset_minutes": tz,
        "base_prep_minutes": base_prep,
        "prep_capacity_per_bucket": capacity,
        "pos_retry_limit": retry_limit,
        "tablet_backlog_threshold": backlog,
        "active_menu_version_id": None,
        "throttle_state": "PAUSED",
        "open_order_count": 0,
        "reserved_prep_slots": 0,
        "tablet_backlog_count": 0,
        "last_published_at": None,
    })
    db.stores[store["id"]] = store
    return response.object_response(serializers.store(store), 201)


@bp.get("/stores/<store_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def read_store(store_id):
    store = common.get_store(store_id)
    M.require_store_scope(store_id)
    return response.object_response(serializers.store(store))


@bp.get("/stores")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER, M.SETTLEMENT_ANALYST)
def list_stores():
    limit, offset = validation.pagination()
    brand_code = validation.query_str("brand_code")
    active_version = validation.query_str("active_menu_version_id")
    throttle_state = validation.query_enum("throttle_state", K.THROTTLE_STATES)

    def keep(rec):
        if brand_code is not None and rec["brand_code"] != brand_code:
            return False
        if active_version is not None and rec["active_menu_version_id"] != active_version:
            return False
        if throttle_state is not None and rec["throttle_state"] != throttle_state:
            return False
        return True

    records = db.sorted_records(db.stores, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.store(r) for r in page], meta)


@bp.patch("/stores/<store_id>")
@M.endpoint(M.PLATFORM_ADMIN)
def update_store(store_id):
    payload = validation.body()
    base_prep = validation.opt_int(payload, "base_prep_minutes", 1, 60)
    capacity = validation.opt_int(payload, "prep_capacity_per_bucket", 1)
    retry_limit = validation.opt_int(payload, "pos_retry_limit", 1, 5)
    backlog = validation.opt_int(payload, "tablet_backlog_threshold", 1)
    store = common.get_store(store_id)

    if base_prep is not None:
        store["base_prep_minutes"] = base_prep
    if capacity is not None:
        store["prep_capacity_per_bucket"] = capacity
    if retry_limit is not None:
        store["pos_retry_limit"] = retry_limit
    if backlog is not None:
        store["tablet_backlog_threshold"] = backlog
    # A capacity revision deliberately does NOT re-derive throttle_state.
    db.touch(store)
    return response.object_response(serializers.store(store))


# --------------------------------------------------------- hour windows ----
@bp.post("/stores/<store_id>/hour-windows")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR)
def create_hour_window(store_id):
    payload = validation.body()
    day = validation.req_int(payload, "day_of_week", 0, 6)
    opens = validation.req_int(payload, "opens_at_minute", 0, 1439)
    closes = validation.req_int(payload, "closes_at_minute", 1, 1440)
    if closes <= opens:
        validation.bad("closes_at_minute must be strictly greater than opens_at_minute.")
    store = common.get_store(store_id)
    M.require_store_scope(store_id)

    for existing in db.hour_windows.values():
        if existing["store_id"] != store["id"] or existing["day_of_week"] != day:
            continue
        if opens < existing["closes_at_minute"] and existing["opens_at_minute"] < closes:
            fail(errors.ERR_HOUR_WINDOW_OVERLAP)

    window = db.record(journal=True)
    window.update({
        "store_id": store["id"],
        "day_of_week": day,
        "opens_at_minute": opens,
        "closes_at_minute": closes,
        "window_minutes": closes - opens,
    })
    db.hour_windows[window["id"]] = window
    return response.object_response(serializers.hour_window(window), 201)


@bp.get("/stores/<store_id>/hour-windows")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def list_hour_windows(store_id):
    limit, offset = validation.pagination()
    day = validation.query_int("day_of_week", 0, 6)
    common.get_store(store_id)
    M.require_store_scope(store_id)

    def keep(rec):
        if rec["store_id"] != store_id:
            return False
        if day is not None and rec["day_of_week"] != day:
            return False
        return True

    records = db.sorted_records(db.hour_windows, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.hour_window(r) for r in page], meta)


# -------------------------------------------------------- publish a menu ----
@bp.post("/stores/<store_id>/publish-menu")
@M.endpoint(M.STORE_OPERATOR)
def publish_menu(store_id):
    payload = validation.body()
    version_id = validation.req_str(payload, "menu_version_id")
    expected = validation.req_int(payload, "expected_store_version")
    store = common.get_store(store_id)
    version = common.get_menu_version(version_id)
    M.require_store_scope(store_id)

    if expected != store["version"]:
        fail(errors.ERR_STALE_STORE_VERSION)
    if version["state"] not in ("PUBLISHED", "EXHAUSTED"):
        fail(errors.ERR_MENU_VERSION_NOT_PUBLISHED)
    if version["brand_code"] != store["brand_code"]:
        fail(errors.ERR_BRAND_MISMATCH)
    if not any(w["store_id"] == store["id"] for w in db.hour_windows.values()):
        fail(errors.ERR_STORE_HOURS_MISSING)

    previous_id = store["active_menu_version_id"]
    previous = db.menu_versions.get(previous_id) if previous_id else None

    # Tear down the listings this store held under the previous version.
    affected_channels = set()
    for listing in list(db.listings.values()):
        if listing["store_id"] == store["id"]:
            affected_channels.add(listing["channel_id"])
            del db.listings[listing["id"]]

    store["active_menu_version_id"] = version["id"]
    store["last_published_at"] = clock.now()
    if store["throttle_state"] == "PAUSED":
        store["throttle_state"] = "NORMAL"

    items = db.sorted_records(db.menu_items,
                              lambda i: i["menu_version_id"] == version["id"])
    channels = db.sorted_records(db.channels)
    for item in items:
        for channel in channels:
            listing = db.record()
            listing.update({
                "store_id": store["id"],
                "channel_id": channel["id"],
                "menu_item_id": item["id"],
                "sku": item["sku"],
                "base_price_cents": item["base_price_cents"],
                "price_cents": domain.listing_price_cents(
                    item["base_price_cents"], channel["markup_bps"],
                    channel["rounding_mode"]),
                "suppressed": False,
                "eighty_sixed": False,
                "availability_state": "AVAILABLE",
            })
            listing["availability_state"] = domain.derive_availability_state(
                listing, channel, store)
            db.listings[listing["id"]] = listing
            affected_channels.add(channel["id"])

    for channel_id in affected_channels:
        domain.recompute_channel_listing_count(db.channels.get(channel_id))

    if previous_id != version["id"]:
        version["published_store_count"] += 1
        db.touch(version)
        if previous is not None:
            previous["published_store_count"] -= 1
            if previous["published_store_count"] <= 0:
                previous["published_store_count"] = max(
                    0, previous["published_store_count"])
                if previous["state"] in ("PUBLISHED", "EXHAUSTED"):
                    previous["state"] = "SUPERSEDED"
                    previous["superseded_at"] = clock.now()
            db.touch(previous)

    db.touch(store)
    return response.object_response(serializers.store(store))


# ------------------------------------------------------ throttle posture ----
@bp.post("/stores/<store_id>/recompute-throttle")
@M.endpoint(M.STORE_OPERATOR)
def recompute_throttle(store_id):
    store = common.get_store(store_id)
    M.require_store_scope(store_id)

    target = domain.throttle_target(store)
    if target != store["throttle_state"]:
        store["throttle_state"] = target
        db.touch(store)
    domain.refresh_store_listing_availability(store)
    return response.object_response(serializers.store(store))


# ---------------------------------------------------------------- quote -----
@bp.get("/stores/<store_id>/quote")
@M.endpoint(M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def store_quote(store_id):
    channel_id = request.args.get("channel_id")
    if channel_id is None or not channel_id.strip():
        validation.bad("Query parameter 'channel_id' is required.")
    mode = request.args.get("fulfillment_mode")
    if mode is None or mode not in K.FULFILLMENT_MODES:
        validation.bad("Query parameter 'fulfillment_mode' must be PICKUP or DELIVERY.")

    store = common.get_store(store_id)
    common.get_channel(channel_id)
    M.require_store_scope(store_id)
    M.require_channel_scope(channel_id)

    if store["active_menu_version_id"] is None:
        fail(errors.ERR_STORE_MENU_NOT_PUBLISHED)
    if domain.store_open_window(store) is None:
        fail(errors.ERR_STORE_CLOSED)

    quote = domain.compute_quote(store, mode, "PROVISIONAL")
    if quote["total_minutes"] > K.MAX_QUOTE_MINUTES:
        fail(errors.ERR_QUOTE_WINDOW_EXCEEDED)

    bucket_index = domain.bucket_index_for(store)
    data = {
        "store_id": store["id"],
        "channel_id": channel_id,
        "variant": "PROVISIONAL",
        "load_count": quote["load_count"],
        "prep_minutes": quote["prep_minutes"],
        "travel_minutes": quote["travel_minutes"],
        "total_minutes": quote["total_minutes"],
        "bucket_index": bucket_index,
        "bucket_load": domain.bucket_load(store, bucket_index),
        "quoted_ready_at": clock.fmt(quote["ready_at"]),
    }
    return response.object_response(data)

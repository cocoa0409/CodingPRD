"""Channel connections + imported reservations (PRD §3.2)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from models import make_entity, serialize, touch
from response import success, list_success
from services.access import get_or_404, fk_or_404, require_host_owns_listing
from services import calendar as cal
from services.listing_util import sort_and_paginate
from util import parse_datetime
from validators import get_body, req_enum, req_str, parse_pagination

bp = Blueprint("channels", __name__)

CHANNELS = {"AIRBNB", "VRBO", "BOOKINGCOM", "DIRECT"}


@bp.post("/channel-connections")
def create_channel():
    user_id, role = require_auth({"Host"})
    body = get_body()
    listing_id = req_str(body, "listing_id")
    listing = fk_or_404(db.listings, listing_id)
    require_host_owns_listing(listing, user_id, role)
    channel = req_enum(body, "channel", CHANNELS)
    conn = make_entity({
        "listing_id": listing_id,
        "channel": channel,
        "status": "DISCONNECTED",
        "pending_sync_count": 0,
        "last_synced_at": None,
    })
    db.channel_connections[conn["id"]] = conn
    return success(serialize(conn), status=201)


@bp.get("/channel-connections/<cid>")
def get_channel(cid):
    require_auth({"Host", "PlatformAdmin"})
    conn = get_or_404(db.channel_connections, cid)
    return success(serialize(conn))


@bp.get("/channel-connections")
def list_channels():
    require_auth({"Host", "PlatformAdmin"})
    limit, offset = parse_pagination()
    listing_id = request.args.get("listing_id")
    items = [c for c in db.channel_connections.values()
             if listing_id is None or c["listing_id"] == listing_id]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


@bp.post("/channel-connections/<cid>/connect")
def connect_channel(cid):
    user_id, role = require_auth({"Host"})
    conn = get_or_404(db.channel_connections, cid)
    listing = db.listings.get(conn["listing_id"])
    require_host_owns_listing(listing, user_id, role)
    if conn["status"] not in ("DISCONNECTED", "ERROR"):
        raise err("ERR_INVALID_STATE", "connect not defined from current state")
    conn["status"] = "CONNECTED"
    touch(conn)
    return success(serialize(conn))


@bp.post("/channel-connections/<cid>/sync")
def sync_channel(cid):
    require_auth({"PlatformAdmin"})
    conn = get_or_404(db.channel_connections, cid)
    if conn["status"] != "CONNECTED":
        raise err("ERR_INVALID_STATE", "sync requires CONNECTED")
    conn["status"] = "SYNCING"
    touch(conn)
    return success(serialize(conn))


@bp.post("/channel-connections/<cid>/sync-complete")
def sync_complete(cid):
    require_auth({"PlatformAdmin"})
    conn = get_or_404(db.channel_connections, cid)
    if conn["status"] != "SYNCING":
        raise err("ERR_INVALID_STATE", "sync-complete requires SYNCING")
    conn["pending_sync_count"] = 0
    conn["last_synced_at"] = db.current_utc
    conn["status"] = "CONNECTED"
    touch(conn)
    return success(serialize(conn))


@bp.post("/channel-connections/<cid>/sync-fail")
def sync_fail(cid):
    require_auth({"PlatformAdmin"})
    conn = get_or_404(db.channel_connections, cid)
    if conn["status"] != "SYNCING":
        raise err("ERR_INVALID_STATE", "sync-fail requires SYNCING")
    # pending_sync_count preserved (PRD §3.2).
    conn["status"] = "ERROR"
    touch(conn)
    return success(serialize(conn))


@bp.post("/channel-connections/<cid>/imported-reservations")
def import_reservation(cid):
    require_auth({"PlatformAdmin"})
    conn = get_or_404(db.channel_connections, cid)
    listing = db.listings.get(conn["listing_id"])
    body = get_body()
    external_ref = req_str(body, "external_ref")
    sd_raw = req_str(body, "start_date")
    ed_raw = req_str(body, "end_date")
    sd = parse_datetime(sd_raw)
    ed = parse_datetime(ed_raw)
    if ed <= sd:
        raise err("ERR_INVALID_DATE_RANGE", "end_date must be after start_date")
    # Duplicate external_ref on the same connection (PRD §3.2).
    for ir in db.imported_reservations.values():
        if ir["channel_connection_id"] == cid and ir["external_ref"] == external_ref:
            raise err("ERR_DUPLICATE_EXTERNAL_REF", "external_ref already exists on connection")

    if cal.interval_available(listing, sd, ed):
        block = cal.create_active_block(listing, "IMPORTED", sd, ed)
        ir = make_entity({
            "channel_connection_id": cid,
            "calendar_block_id": block["id"],
            "external_ref": external_ref,
            "start_date": sd,
            "end_date": ed,
            "import_status": "ACCEPTED",
        })
    else:
        ir = make_entity({
            "channel_connection_id": cid,
            "calendar_block_id": None,
            "external_ref": external_ref,
            "start_date": sd,
            "end_date": ed,
            "import_status": "REJECTED_OVERLAP",
        })
    db.imported_reservations[ir["id"]] = ir
    return success(serialize(ir), status=201)


@bp.get("/imported-reservations/<iid>")
def get_imported(iid):
    require_auth({"Host", "PlatformAdmin"})
    ir = get_or_404(db.imported_reservations, iid)
    return success(serialize(ir))


@bp.get("/channel-connections/<cid>/imported-reservations")
def list_channel_imported(cid):
    require_auth({"Host", "PlatformAdmin"})
    get_or_404(db.channel_connections, cid)
    limit, offset = parse_pagination()
    import_status = request.args.get("import_status")
    items = [ir for ir in db.imported_reservations.values()
             if ir["channel_connection_id"] == cid
             and (import_status is None or ir["import_status"] == import_status)]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


@bp.get("/imported-reservations")
def list_imported():
    require_auth({"Host", "PlatformAdmin"})
    limit, offset = parse_pagination()
    ccid = request.args.get("channel_connection_id")
    cbid = request.args.get("calendar_block_id")
    import_status = request.args.get("import_status")
    items = []
    for ir in db.imported_reservations.values():
        if ccid is not None and ir["channel_connection_id"] != ccid:
            continue
        if cbid is not None and ir["calendar_block_id"] != cbid:
            continue
        if import_status is not None and ir["import_status"] != import_status:
            continue
        items.append(ir)
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)

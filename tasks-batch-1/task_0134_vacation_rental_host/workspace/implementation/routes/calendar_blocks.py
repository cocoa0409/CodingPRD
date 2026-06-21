"""Calendar blocks: create MANUAL (OCC-guarded), fetch, list, release (PRD §3.3)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from models import serialize, touch
from response import success, list_success
from services.access import get_or_404, require_host_owns_listing
from services import calendar as cal
from services.listing_util import sort_and_paginate
from util import parse_datetime
from validators import get_body, req_enum, req_str, req_int, parse_pagination, require

bp = Blueprint("calendar_blocks", __name__)

BLOCK_SOURCES = {"BOOKING", "MANUAL", "IMPORTED"}


@bp.post("/listings/<lid>/calendar-blocks")
def create_block(lid):
    user_id, role = require_auth({"Host"})
    listing = get_or_404(db.listings, lid)
    require_host_owns_listing(listing, user_id, role)
    body = get_body()
    source = req_enum(body, "source", BLOCK_SOURCES)
    sd_raw = req_str(body, "start_date")
    ed_raw = req_str(body, "end_date")
    expected = req_int(body, "expected_listing_calendar_version")

    sd = parse_datetime(sd_raw)
    ed = parse_datetime(ed_raw)
    # ERR_INVALID_DATE_RANGE (priority 9) before availability (11) and OCC (15).
    if ed <= sd:
        raise err("ERR_INVALID_DATE_RANGE", "end_date must be after start_date")
    # Availability + gap (priority 11).
    if not cal.interval_available(listing, sd, ed):
        raise err("ERR_DATES_UNAVAILABLE", "interval overlaps a block or violates gap")
    # OCC (priority 15).
    if expected != listing["calendar_version"]:
        raise err("ERR_STALE_CALENDAR_VERSION", "stale calendar version")

    # Create ACTIVE block; advance calendar_version + propagate to channels.
    block = cal.create_active_block(listing, source, sd, ed)
    # PRD §3.3: the listing's common version increments by 1 on a manual block create.
    # advance_calendar_and_propagate already touched the listing once for the
    # calendar_version advance; that single bump satisfies "version increments by 1".
    return success(serialize(block), status=201)


@bp.get("/calendar-blocks/<bid>")
def get_block(bid):
    require_auth({"Host", "Guest", "PlatformAdmin"})
    block = get_or_404(db.calendar_blocks, bid)
    return success(serialize(block))


@bp.get("/listings/<lid>/calendar-blocks")
def list_blocks(lid):
    require_auth({"Host", "Guest", "PlatformAdmin"})
    get_or_404(db.listings, lid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [b for b in db.calendar_blocks.values()
             if b["listing_id"] == lid and (status is None or b["status"] == status)]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


@bp.post("/listings/<lid>/calendar-blocks/<bid>/release")
def release_block(lid, bid):
    user_id, role = require_auth({"Host"})
    # Path validated left-to-right: listing then block.
    listing = get_or_404(db.listings, lid)
    block = get_or_404(db.calendar_blocks, bid)
    if block["listing_id"] != lid:
        raise err("ERR_NOT_FOUND", "block does not belong to listing")
    require_host_owns_listing(listing, user_id, role)
    # A BOOKING-source block may never be released manually (PRD §3.3).
    if block["source"] == "BOOKING":
        raise err("ERR_RELEASE_BOOKING_BLOCK", "booking-origin blocks release via cancel/decline")
    if block["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "block is not ACTIVE")
    cal.release_block(block, listing)
    return success(serialize(block))

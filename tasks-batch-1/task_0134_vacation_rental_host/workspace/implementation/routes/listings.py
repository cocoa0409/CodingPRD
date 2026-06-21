"""Listings: create, fetch, list, publish/snooze, quote (PRD §3.1, §3.4)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from models import make_entity, serialize, touch
from response import success, list_success
from services.access import get_or_404, fk_or_404, require_host_owns_listing
from services import calc
from services.listing_util import sort_and_paginate
from util import parse_datetime
from validators import (
    get_body, req_str, req_int, opt_int, opt_enum, check_range, parse_pagination,
    require,
)

bp = Blueprint("listings", __name__)

CANCELLATION_TIERS = {"FLEXIBLE", "MODERATE", "STRICT"}


@bp.post("/listings")
def create_listing():
    user_id, role = require_auth({"Host"})
    body = get_body()
    host_id = req_str(body, "host_id")
    # Body FK existence (priority 4) before ownership.
    fk_or_404(db.hosts, host_id)
    # A Host caller may only create a listing owned by themselves (PRD §2.1).
    if role == "Host" and host_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "host_id must match the acting host")

    title = req_str(body, "title")
    base_rate = req_int(body, "base_nightly_rate_cents")
    check_range(base_rate, "base_nightly_rate_cents", lo=1)
    cleaning = req_int(body, "cleaning_fee_cents")
    check_range(cleaning, "cleaning_fee_cents", lo=0)

    pet_fee = opt_int(body, "pet_fee_cents", 0)
    check_range(pet_fee, "pet_fee_cents", lo=0)
    tax_rate = opt_int(body, "tax_rate_bps", 0)
    check_range(tax_rate, "tax_rate_bps", lo=0, hi=2000)
    min_nights = opt_int(body, "min_nights", 1)
    check_range(min_nights, "min_nights", lo=1)
    gap_nights = opt_int(body, "gap_nights", 0)
    check_range(gap_nights, "gap_nights", lo=0)
    cancellation_tier = opt_enum(body, "cancellation_tier", CANCELLATION_TIERS, "MODERATE")
    security_deposit = opt_int(body, "security_deposit_cents", 0)
    check_range(security_deposit, "security_deposit_cents", lo=0)
    commission = opt_int(body, "platform_commission_bps", 1500)
    check_range(commission, "platform_commission_bps", lo=0, hi=3000)
    payout_delay = opt_int(body, "payout_delay_days", 1)
    check_range(payout_delay, "payout_delay_days", lo=0)

    listing = make_entity({
        "host_id": host_id,
        "title": title,
        "base_nightly_rate_cents": base_rate,
        "cleaning_fee_cents": cleaning,
        "pet_fee_cents": pet_fee,
        "tax_rate_bps": tax_rate,
        "min_nights": min_nights,
        "gap_nights": gap_nights,
        "cancellation_tier": cancellation_tier,
        "security_deposit_cents": security_deposit,
        "platform_commission_bps": commission,
        "payout_delay_days": payout_delay,
        "calendar_version": 1,
        "status": "DRAFT",
    })
    db.listings[listing["id"]] = listing
    return success(serialize(listing), status=201)


@bp.get("/listings/<lid>")
def get_listing(lid):
    require_auth({"Host", "Guest", "PlatformAdmin"})
    listing = get_or_404(db.listings, lid)
    return success(serialize(listing))


@bp.get("/listings")
def list_listings():
    require_auth({"Host", "Guest", "PlatformAdmin"})
    limit, offset = parse_pagination()
    host_id = request.args.get("host_id")
    items = [l for l in db.listings.values()
             if host_id is None or l["host_id"] == host_id]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)


@bp.post("/listings/<lid>/publish")
def publish_listing(lid):
    user_id, role = require_auth({"Host"})
    listing = get_or_404(db.listings, lid)
    require_host_owns_listing(listing, user_id, role)
    status = listing["status"]
    if status == "DRAFT":
        # Must have >= 1 RatePlan with non-empty window coverage.
        plans = [rp for rp in db.rate_plans.values() if rp["listing_id"] == lid]
        has_coverage = any(
            rp["window_end"] >= rp["window_start"] for rp in plans
        )
        if not has_coverage:
            raise err("ERR_INVALID_STATE", "listing has no rate plan coverage to publish")
        listing["status"] = "LISTED"
        touch(listing)
    elif status == "SNOOZED":
        listing["status"] = "LISTED"
        touch(listing)
    else:
        raise err("ERR_INVALID_STATE", "publish not defined from current state")
    return success(serialize(listing))


@bp.post("/listings/<lid>/snooze")
def snooze_listing(lid):
    user_id, role = require_auth({"Host"})
    listing = get_or_404(db.listings, lid)
    require_host_owns_listing(listing, user_id, role)
    if listing["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "snooze not defined from current state")
    listing["status"] = "SNOOZED"
    touch(listing)
    return success(serialize(listing))


@bp.get("/listings/<lid>/quote")
def quote_listing(lid):
    require_auth({"Host", "Guest", "PlatformAdmin"})
    listing = get_or_404(db.listings, lid)
    check_in = request.args.get("check_in")
    check_out = request.args.get("check_out")
    if not check_in or not check_out:
        raise err("ERR_VALIDATION", "check_in and check_out are required")
    ci = parse_datetime(check_in)
    co = parse_datetime(check_out)
    if co <= ci:
        raise err("ERR_INVALID_DATE_RANGE", "check_out must be after check_in")
    pets_raw = request.args.get("pets_count")
    if pets_raw is None or pets_raw == "":
        pets_count = 0
    else:
        try:
            pets_count = int(pets_raw)
        except ValueError:
            raise err("ERR_VALIDATION", "pets_count must be an integer")
        check_range(pets_count, "pets_count", lo=0)

    rate_plans = [rp for rp in db.rate_plans.values() if rp["listing_id"] == lid]
    nightly = calc.nightly_pricing(listing, rate_plans, ci, co)
    fees, tax, total = calc.booking_total(listing, nightly, pets_count)
    return success({
        "nightly_subtotal_cents": nightly,
        "fees_cents": fees,
        "tax_cents": tax,
        "total_cents": total,
    })

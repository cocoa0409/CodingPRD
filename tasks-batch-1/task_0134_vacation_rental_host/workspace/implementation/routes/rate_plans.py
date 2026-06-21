"""Rate plans: create (closed-interval overlap check), fetch, list (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from models import make_entity, serialize
from response import success, list_success
from services.access import get_or_404, fk_or_404, require_host_owns_listing
from services.listing_util import sort_and_paginate
from util import parse_datetime, date_only
from validators import (
    get_body, req_str, req_int, opt_int, check_range, parse_pagination,
)

bp = Blueprint("rate_plans", __name__)


@bp.post("/rate-plans")
def create_rate_plan():
    user_id, role = require_auth({"Host"})
    body = get_body()
    listing_id = req_str(body, "listing_id")
    listing = fk_or_404(db.listings, listing_id)
    require_host_owns_listing(listing, user_id, role)

    label = req_str(body, "label")
    ws_raw = req_str(body, "window_start")
    we_raw = req_str(body, "window_end")
    seasonal = req_int(body, "seasonal_multiplier_bps")
    check_range(seasonal, "seasonal_multiplier_bps", lo=1, hi=50000)
    weekend = opt_int(body, "weekend_multiplier_bps", 10000)
    check_range(weekend, "weekend_multiplier_bps", lo=1, hi=50000)

    ws = parse_datetime(ws_raw)
    we = parse_datetime(we_raw)
    # window_end strictly after window_start (PRD §3.1).
    if we <= ws:
        raise err("ERR_INVALID_DATE_RANGE", "window_end must be after window_start")

    # Closed-interval overlap check against existing plans on the same listing.
    new_s = date_only(ws)
    new_e = date_only(we)
    for rp in db.rate_plans.values():
        if rp["listing_id"] != listing_id:
            continue
        es = date_only(rp["window_start"])
        ee = date_only(rp["window_end"])
        # Closed intervals overlap iff new_s <= ee and es <= new_e.
        if new_s <= ee and es <= new_e:
            raise err("ERR_RATE_PLAN_OVERLAP", "rate plan window overlaps an existing plan")

    rp = make_entity({
        "listing_id": listing_id,
        "label": label,
        "window_start": ws,
        "window_end": we,
        "seasonal_multiplier_bps": seasonal,
        "weekend_multiplier_bps": weekend,
    })
    db.rate_plans[rp["id"]] = rp
    return success(serialize(rp), status=201)


@bp.get("/rate-plans/<rid>")
def get_rate_plan(rid):
    require_auth({"Host", "Guest", "PlatformAdmin"})
    rp = get_or_404(db.rate_plans, rid)
    return success(serialize(rp))


@bp.get("/rate-plans")
def list_rate_plans():
    require_auth({"Host", "Guest", "PlatformAdmin"})
    limit, offset = parse_pagination()
    listing_id = request.args.get("listing_id")
    items = [rp for rp in db.rate_plans.values()
             if listing_id is None or rp["listing_id"] == listing_id]
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)

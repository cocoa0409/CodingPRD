"""Test-driving endpoints: /_clock/set_current_utc, /_ops/decay-strikes."""
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import clock, parse_iso
from errors import raise_error
from middleware import require_auth
from response import ok
from services.calc import REASON_WEIGHTS

bp = Blueprint("test_ops", __name__)


@bp.post("/_clock/set_current_utc")
@require_auth(["PlatformAdmin"])
def set_clock():
    body = request.get_json(silent=True) or {}
    if "to_iso8601" not in body:
        raise_error("ERR_INVALID_REQUEST", "to_iso8601 required")
    try:
        clock.set_from_iso(body["to_iso8601"])
    except Exception:
        raise_error("ERR_INVALID_REQUEST", "invalid iso8601")
    return ok({})


@bp.post("/_ops/decay-strikes")
@require_auth(["PlatformAdmin"])
def decay_strikes():
    """Full-recompute variant per PRD §3.8:
    walk every creator's trailing-90-day APPROVED CONSUMER_FAULT ReprintRequests,
    sum weights by reason_code, overwrite reprint_strike_count.
    """
    now = clock.now()
    window_start = now - timedelta(days=90)

    for creator in db.creators.all():
        # Build the request set scoped to this creator via reprint -> job -> order -> listing -> storefront -> creator.
        score = 0
        for req in db.reprint_requests.all():
            if req["status"] != "APPROVED":
                continue
            if req["fault_category"] != "CONSUMER_FAULT":
                continue
            job = db.fulfillment_jobs.get(req["job_id"])
            if not job:
                continue
            order = db.orders.get(job["order_id"])
            if not order:
                continue
            listing = db.listings.get(order["listing_id"])
            if not listing:
                continue
            storefront = db.storefronts.get(listing["storefront_id"])
            if not storefront:
                continue
            if storefront["creator_id"] != creator["id"]:
                continue
            # 90-day window on req.updated_at (half-open [now-90d, now)).
            u = parse_iso(req["updated_at"])
            if u < window_start or u >= now:
                continue
            score += REASON_WEIGHTS.get(req["reason_code"], 0)

        if creator["reprint_strike_count"] != score:
            creator["reprint_strike_count"] = score
            db.bump(creator)

    return ok({})

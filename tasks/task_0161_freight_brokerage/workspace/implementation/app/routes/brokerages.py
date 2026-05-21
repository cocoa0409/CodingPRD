"""Brokerage CRUD + server-clock + quote-expiry sweep."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import ApiError, ERR_INVALID_REQUEST
from ..helpers import (
    check_version,
    get_body,
    get_brokerage_or_404,
    optional_field,
    require_field,
    require_iso,
)
from ..services.quotes import expire_quotes
from ..store import store
from ..timeutil import iso_now


brokerages_bp = Blueprint("brokerages", __name__, url_prefix="/brokerages")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@brokerages_bp.post("")
@require_auth(["PlatformAdmin"])
def create_brokerage():
    body = get_body()

    name = require_field(body, "name", str)
    mc_number = require_field(body, "mc_number", str)

    # factoring_reserve_pct: number 0..100, two decimals.
    if "factoring_reserve_pct" not in body or body["factoring_reserve_pct"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: factoring_reserve_pct")
    raw_pct = body["factoring_reserve_pct"]
    if isinstance(raw_pct, bool) or not isinstance(raw_pct, (int, float, Decimal)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "factoring_reserve_pct must be a number.")
    pct = float(raw_pct)
    if pct < 0 or pct > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400, "factoring_reserve_pct must be in [0, 100].")

    detention_free = optional_field(body, "detention_free_minutes", int, default=120)
    detention_rate = optional_field(body, "detention_rate_cents_per_15min", int, default=1500)
    if detention_free < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "detention_free_minutes must be non-negative.")
    if detention_rate < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "detention_rate_cents_per_15min must be non-negative.")

    with store.lock:
        now = iso_now()
        bk = {
            "name": name,
            "mc_number": mc_number,
            "factoring_reserve_pct": pct,
            "detention_free_minutes": int(detention_free),
            "detention_rate_cents_per_15min": int(detention_rate),
            "clock_now_iso": now,
        }
        store.stamp_create(bk, now=now)
        store.brokerages[bk["id"]] = bk
    return ok_object(bk, status=201)


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------
@brokerages_bp.get("/<brokerage_id>")
@require_auth(["PlatformAdmin", "BrokerOps", "CarrierOps", "ShipperUser", "CarrierUser"])
def get_brokerage(brokerage_id):
    bk = get_brokerage_or_404(brokerage_id)
    return ok_object(bk)


# ---------------------------------------------------------------------------
# Clock advance (test driver)
# ---------------------------------------------------------------------------
@brokerages_bp.post("/<brokerage_id>/_clock/advance")
@require_auth(["PlatformAdmin"])
def clock_advance(brokerage_id):
    body = get_body()
    target = require_iso(body, "to_iso")
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        check_version(bk, body)
        # PRD §2.5 — clock never moves backward
        # (the spec doesn't explicitly errror on backward — treat as no-op set forward only)
        from ..timeutil import parse_iso
        current = parse_iso(bk["clock_now_iso"])
        if target < current:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Clock cannot move backward.")
        bk["clock_now_iso"] = iso_now(target)
        store.bump(bk)
        expire_quotes(brokerage_id)
    return ok_object(bk)


# ---------------------------------------------------------------------------
# Manual quote-expiry sweep
# ---------------------------------------------------------------------------
@brokerages_bp.post("/<brokerage_id>/_sweep/expire-quotes")
@require_auth(["PlatformAdmin"])
def sweep_expire_quotes(brokerage_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        swept = expire_quotes(brokerage_id)
    return ok_array(
        swept,
        limit=len(swept),
        offset=0,
        total_count=len(swept),
        has_more=False,
    )

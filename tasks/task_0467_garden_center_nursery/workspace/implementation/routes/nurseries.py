"""Nursery + logical clock endpoints."""
from flask import Blueprint

import errors
from clock import clock, parse_iso8601, to_iso8601_millis
from db import db, base_versioned
from errors import err
from lookups import body, get_nursery
from middleware import require_roles
from response import ok, created
from validation import (req_str, req_int_in_range, opt_int)

bp = Blueprint("nurseries", __name__)


def _nursery_view(n):
    return {
        "id": n["id"],
        "name": n["name"],
        "site_hardiness_zone": n["site_hardiness_zone"],
        "loyalty_accrual_per_dollar": n["loyalty_accrual_per_dollar"],
        "gold_tier_threshold_points": n["gold_tier_threshold_points"],
        "shrink_writeoff_zone_grace": n["shrink_writeoff_zone_grace"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


@bp.post("/nurseries")
@require_roles("PlatformAdmin")
def create_nursery():
    data = body()
    name = req_str(data, "name")
    zone = req_int_in_range(data, "site_hardiness_zone", 1, 13)
    accrual = opt_int(data, "loyalty_accrual_per_dollar", 1)
    gold = opt_int(data, "gold_tier_threshold_points", 1000)
    grace = opt_int(data, "shrink_writeoff_zone_grace", 2)

    n = base_versioned()
    n.update({
        "name": name,
        "site_hardiness_zone": zone,
        "loyalty_accrual_per_dollar": accrual,
        "gold_tier_threshold_points": gold,
        "shrink_writeoff_zone_grace": grace,
    })
    db.nurseries[n["id"]] = n
    return created(_nursery_view(n))


@bp.get("/nurseries/<nursery_id>")
@require_roles("PlatformAdmin", "InventoryManager", "SalesClerk")
def read_nursery(nursery_id):
    n = get_nursery(nursery_id)
    return ok(_nursery_view(n))


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        err(errors.ERR_INVALID_REQUEST, "to_iso8601 required")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be ISO-8601")
    clock.set(dt)
    return ok({"now": to_iso8601_millis(clock.get())})

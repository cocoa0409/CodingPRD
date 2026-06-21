"""Mini-Golf & Go-Kart Track API — Flask entry point.

In-memory only. Store starts empty on every boot (no seeding).
"""
import os
from datetime import timedelta

from flask import Flask, request

from db import db
from errors import ApiError, err
import errors as E
import response as R
from middleware import (
    authenticate, require_role, forbid,
    ROLE_OPS, ROLE_CASHIER, ROLE_GUEST,
)
import reqvalidate as V
from pagination import get_pagination, paginate
from util import new_uuid, now_iso, parse_iso, parse_date, iso_format
import serializers as S
import services as SV
import calculations as C

app = Flask(__name__)

ALL_ROLES = [ROLE_OPS, ROLE_CASHIER, ROLE_GUEST]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return R.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return R.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return R.error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return R.error(e.error_id, e.message, e.http_status)
    return R.error("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 422)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def base_entity_fields():
    ts = now_iso()
    return {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def guest_owns(principal, *guest_ids):
    """For a Guest principal, ensure X-User-ID matches one of the guest ids.

    OpsManager and Cashier always pass.
    """
    if not principal.is_guest:
        return
    for gid in guest_ids:
        if gid is not None and gid == principal.user_id:
            return
    forbid()


def list_response(collection, sort_items, ser, filters):
    """Generic list endpoint: filter, sort by created_at ASC, paginate."""
    items = list(collection.values())
    for key, val in filters.items():
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    limit, offset = get_pagination()
    total = len(items)
    page = paginate(items, limit, offset)
    return R.success_list([ser(x) for x in page], limit, offset, total)


# ===========================================================================
# VENUE
# ===========================================================================

@app.route("/venues", methods=["POST"])
def create_venue():
    p = authenticate()
    require_role(p, [ROLE_OPS])
    body = V.get_json_body()
    name = V.require_str(body, "name")
    timezone = V.optional_str(body, "timezone", "America/New_York")
    v = base_entity_fields()
    v.update({
        "name": name,
        "timezone": timezone,
        "posture": "OPEN",
        "weather_hold_reason": None,
        "current_utc": v["created_at"],
    })
    db.venues[v["id"]] = v
    return R.success(S.venue_out(v), 201)


@app.route("/venues", methods=["GET"])
def list_venues():
    p = authenticate()
    require_role(p, ALL_ROLES)
    posture = request.args.get("posture")
    return list_response(db.venues, None, S.venue_out, {"posture": posture})


@app.route("/venues/<venue_id>", methods=["GET"])
def get_venue_ep(venue_id):
    p = authenticate()
    require_role(p, ALL_ROLES)
    v = SV.get_venue(venue_id)
    return R.success(S.venue_out(v))


@app.route("/venues/<venue_id>/weather-hold", methods=["POST"])
def venue_weather_hold(venue_id):
    p = authenticate()
    require_role(p, [ROLE_OPS])
    v = SV.get_venue(venue_id)
    body = V.get_json_body()
    reason = V.require_str(body, "weather_hold_reason")
    # expected_venue_version is accepted but NOT OCC-enforced: PRD §2.8 names
    # only slot and group confirms as guarded; "endpoints not named here
    # perform no OCC check."
    SV.weather_hold(v, reason)
    return R.success(S.venue_out(v))


@app.route("/venues/<venue_id>/resume", methods=["POST"])
def venue_resume(venue_id):
    p = authenticate()
    require_role(p, [ROLE_OPS])
    v = SV.get_venue(venue_id)
    SV.resume(v)
    return R.success(S.venue_out(v))


@app.route("/venues/<venue_id>/close", methods=["POST"])
def venue_close(venue_id):
    p = authenticate()
    require_role(p, [ROLE_OPS])
    v = SV.get_venue(venue_id)
    SV.close_venue(v)
    return R.success(S.venue_out(v))


@app.route("/venues/<venue_id>/_clock/set_current_utc", methods=["POST"])
def venue_set_clock(venue_id):
    p = authenticate()
    require_role(p, [ROLE_OPS])
    v = SV.get_venue(venue_id)
    body = V.get_json_body()
    raw = V.require_str(body, "to_iso8601")
    try:
        dt = parse_iso(raw)
    except Exception:
        raise err(E.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    if dt is None:
        raise err(E.ERR_INVALID_REQUEST, "to_iso8601 is required")
    v["current_utc"] = iso_format(dt)
    # Setting the clock is a system action; the spec frames it as test-driving.
    # It does not bump version (not a domain mutation per §3.1 narrative).
    return R.success(S.venue_out(v))


# ===========================================================================
# ATTRACTION
# ===========================================================================

@app.route("/attractions", methods=["POST"])
def create_attraction():
    p = authenticate()
    require_role(p, [ROLE_OPS])
    body = V.get_json_body()
    venue_id = V.require_str(body, "venue_id")
    venue = SV.get_venue(venue_id)
    name = V.require_str(body, "name")
    kind = V.require_enum(body, "kind", {"GO_KART", "MINI_GOLF", "ARCADE"})
    min_height = V.optional_int(body, "min_height_cm", 0, minimum=0)
    lane_count = V.optional_int(body, "lane_count", 0, minimum=0)
    a = base_entity_fields()
    a.update({
        "venue_id": venue_id,
        "name": name,
        "kind": kind,
        "min_height_cm": min_height,
        "lane_count": lane_count,
        "status": "ACTIVE",
    })
    db.attractions[a["id"]] = a
    return R.success(S.attraction_out(a), 201)


@app.route("/attractions", methods=["GET"])
def list_attractions():
    p = authenticate()
    require_role(p, ALL_ROLES)
    return list_response(db.attractions, None, S.attraction_out, {
        "venue_id": request.args.get("venue_id"),
        "kind": request.args.get("kind"),
    })


@app.route("/attractions/<attraction_id>", methods=["GET"])
def get_attraction_ep(attraction_id):
    p = authenticate()
    require_role(p, ALL_ROLES)
    a = SV.get_attraction(attraction_id)
    return R.success(S.attraction_out(a))


# ===========================================================================
# PRICING PLAN
# ===========================================================================

@app.route("/pricing-plans", methods=["POST"])
def create_pricing_plan():
    p = authenticate()
    require_role(p, [ROLE_OPS])
    body = V.get_json_body()
    venue_id = V.require_str(body, "venue_id")
    venue = SV.get_venue(venue_id)
    name = V.require_str(body, "name")
    mode = V.require_enum(body, "mode", {"PER_ROUND", "PER_HEAT", "WRISTBAND"})
    base_price = V.require_int(body, "base_price_cents", minimum=0)
    peak = V.optional_int(body, "peak_surcharge_cents", 0, minimum=0)
    group_disc = V.optional_number(body, "group_discount_pct", 0, minimum=0, maximum=0.5)
    wb_cap = V.optional_int(body, "wristband_unit_cap", 0, minimum=0)
    pl = base_entity_fields()
    pl.update({
        "venue_id": venue_id,
        "name": name,
        "mode": mode,
        "base_price_cents": base_price,
        "peak_surcharge_cents": peak,
        "group_discount_pct": group_disc,
        "wristband_unit_cap": wb_cap,
        "status": "ACTIVE",
    })
    db.pricing_plans[pl["id"]] = pl
    return R.success(S.pricing_plan_out(pl), 201)


@app.route("/pricing-plans", methods=["GET"])
def list_pricing_plans():
    p = authenticate()
    require_role(p, ALL_ROLES)
    return list_response(db.pricing_plans, None, S.pricing_plan_out, {
        "venue_id": request.args.get("venue_id"),
        "mode": request.args.get("mode"),
    })


@app.route("/pricing-plans/<plan_id>", methods=["GET"])
def get_pricing_plan_ep(plan_id):
    p = authenticate()
    require_role(p, ALL_ROLES)
    pl = SV.get_pricing_plan(plan_id)
    return R.success(S.pricing_plan_out(pl))


# ---------------------------------------------------------------------------
# Register remaining routes
# ---------------------------------------------------------------------------
import routes_more  # noqa: E402

routes_more.register(app, {
    "base_entity_fields": base_entity_fields,
    "guest_owns": guest_owns,
    "list_response": list_response,
})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

"""Market endpoints."""

from flask import Blueprint, request

from db import store
from errors import ApiError, invalid_request, not_found
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from serializers import market_json
from services.domain import touch, sweep_clock
from timeutil import new_id, iso_now_ms

import re

bp = Blueprint("markets", __name__)

MARKET_CODE_RE = re.compile(r"^[A-Z0-9-]{2,12}$")


def _validate_market_payload(data, partial=False):
    if not partial:
        for f in ("market_code", "display_name", "pricing_multiplier_bps", "standard_turnaround_hours"):
            if f not in data:
                raise invalid_request(f"Missing required field: {f}")
    if "market_code" in data:
        mc = data["market_code"]
        if not isinstance(mc, str) or not MARKET_CODE_RE.match(mc):
            raise invalid_request("market_code must be 2-12 chars of uppercase alphanumerics and dashes")
    if "pricing_multiplier_bps" in data:
        v = data["pricing_multiplier_bps"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 5000 or v > 30000:
            raise invalid_request("pricing_multiplier_bps must be 5000..30000")
    if "standard_turnaround_hours" in data:
        v = data["standard_turnaround_hours"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 12 or v > 120:
            raise invalid_request("standard_turnaround_hours must be 12..120")
    if "twilight_slot_minutes" in data:
        v = data["twilight_slot_minutes"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 30 or v > 120 or v % 15 != 0:
            raise invalid_request("twilight_slot_minutes must be 30..120 in multiples of 15")
    if "travel_buffer_minutes" in data:
        v = data["travel_buffer_minutes"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 180:
            raise invalid_request("travel_buffer_minutes must be 0..180")
    if "weather_reschedule_credit_bps" in data:
        v = data["weather_reschedule_credit_bps"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 5000:
            raise invalid_request("weather_reschedule_credit_bps must be 0..5000")
    if "status" in data:
        if data["status"] not in ("ACTIVE", "SUSPENDED"):
            raise invalid_request("status must be ACTIVE or SUSPENDED")


@bp.route("/markets", methods=["POST"])
def create_market():
    require_roles("OpsAdmin")
    data = request.get_json(silent=True) or {}
    _validate_market_payload(data, partial=False)
    # uniqueness
    for m in store.markets.values():
        if m["market_code"] == data["market_code"]:
            raise invalid_request("market_code must be unique")
    now = iso_now_ms()
    m = {
        "id": new_id(),
        "market_code": data["market_code"],
        "display_name": data["display_name"],
        "pricing_multiplier_bps": data["pricing_multiplier_bps"],
        "standard_turnaround_hours": data["standard_turnaround_hours"],
        "twilight_slot_minutes": data.get("twilight_slot_minutes", 60),
        "travel_buffer_minutes": data.get("travel_buffer_minutes", 45),
        "weather_reschedule_credit_bps": data.get("weather_reschedule_credit_bps", 1000),
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.markets[m["id"]] = m
    return success_object(market_json(m), http_status=201)


@bp.route("/markets", methods=["GET"])
def list_markets():
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted(store.markets.values(), key=lambda m: m["created_at"])
    if status is not None:
        items = [m for m in items if m["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([market_json(m) for m in page], limit, offset, total)


@bp.route("/markets/<marketId>", methods=["GET"])
def get_market(marketId):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    m = store.markets.get(marketId)
    if not m:
        raise not_found("Market not found")
    return success_object(market_json(m))


@bp.route("/markets/<marketId>", methods=["PATCH"])
def patch_market(marketId):
    require_roles("OpsAdmin")
    m = store.markets.get(marketId)
    if not m:
        raise not_found("Market not found")
    data = request.get_json(silent=True) or {}
    _validate_market_payload(data, partial=True)
    for f in ("pricing_multiplier_bps", "standard_turnaround_hours", "twilight_slot_minutes",
              "travel_buffer_minutes", "weather_reschedule_credit_bps", "status"):
        if f in data:
            m[f] = data[f]
    touch(m)
    return success_object(market_json(m))

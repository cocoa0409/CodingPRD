"""Shared helpers: record lifecycle, serialization, resolution, validation,
pagination. Common fields per PRD 2.4: id / created_at / updated_at / version.
"""
from datetime import datetime

from flask import request

import clock
import db
from dates import fmt_dt, parse_dt
from errors import ApiError, not_found, validation
from response import success_list
from services import posture

CATEGORIES = {"FOOD_BEVERAGE", "CRAFT", "APPAREL", "HOME_GOODS", "EXPERIENCE"}
BOOTH_TYPES = {"STANDARD", "CHALET"}
ZONES = {"NORTH", "SOUTH", "EAST", "WEST"}
PERMIT_TYPES = {"TEMP_STRUCTURE", "FOOD_SERVICE", "PROPANE_HEAT", "GENERATOR"}
HOOKUP_TYPES = {"ELECTRIC_15A", "ELECTRIC_30A", "WATER", "PROPANE"}
SLOT_KINDS = {"MUSIC", "DEMO", "SANTA_PHOTOS", "WORKSHOP", "PARADE"}
DIRECTIONS = {"LOAD_IN", "LOAD_OUT"}
PRECIPITATIONS = {"NONE", "RAIN", "SNOW", "ICE"}
SOURCES = {"NWS", "ON_SITE_SENSOR", "OPERATOR"}
DECISIONS = {"ACCEPTED", "REJECTED", "WAITLISTED"}
FORFEIT_REASONS = {"NO_SHOW", "PERMIT_REVOKED", "OPERATOR_EJECTION"}


# ---------------------------------------------------------------- records
def base_record():
    n = clock.now()
    return {
        "id": db.new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Every mutation refreshes updated_at and increments version by 1."""
    rec["updated_at"] = clock.now()
    rec["version"] += 1


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out


def serialize_market(m):
    out = serialize(m)
    mid = m["id"]
    out["posture"] = posture.derive_posture(m)
    out["total_accepted_vendors"] = sum(
        1
        for a in db.STORES["applications"].values()
        if a["market_id"] == mid and a["status"] == "ACCEPTED"
    )
    out["total_booths_committed"] = sum(
        1
        for a in db.STORES["assignments"].values()
        if a["market_id"] == mid and a["status"] == "ACTIVE"
    )
    return out


# ---------------------------------------------------------------- resolution
def get_market(market_id):
    rec = db.STORES["markets"].get(market_id)
    if rec is None:
        raise not_found("market not found")
    return rec


def get_vendor(vendor_id):
    rec = db.STORES["vendors"].get(vendor_id)
    if rec is None:
        raise not_found("vendor not found")
    return rec


def get_child(store, child_id, market_id=None):
    rec = db.STORES[store].get(child_id)
    if rec is None or (market_id is not None and rec.get("market_id") != market_id):
        raise not_found("resource not found")
    return rec


def resolve_nested(store, market_id, child_id):
    """Left-to-right path validation: market first, then child within market."""
    get_market(market_id)
    return get_child(store, child_id, market_id)


# ---------------------------------------------------------------- body validation
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise validation("request body must be a JSON object")
    return data


def required(data, name):
    if name not in data or data[name] is None:
        raise validation("missing required field: %s" % name)
    return data[name]


def as_str(value, name):
    if not isinstance(value, str):
        raise validation("field %s must be a string" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation("field %s must be an integer" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise validation("field %s must be a boolean" % name)
    return value


def as_dt(value, name):
    try:
        return parse_dt(value)
    except (ValueError, TypeError):
        raise validation("field %s must be an ISO-8601 datetime" % name)


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise validation("field %s must be one of %s" % (name, sorted(allowed)))
    return value


def as_dict(value, name):
    if not isinstance(value, dict):
        raise validation("field %s must be an object" % name)
    return value


# ---------------------------------------------------------------- pagination
def page_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


def list_response(records, serializer=None):
    serializer = serializer or serialize
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = page_params()
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)


def arg(name):
    return request.args.get(name)


def arg_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in ("true", "1", "yes")

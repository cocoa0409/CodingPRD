"""Shared helpers: validation, common fields, pagination, datetime parsing, money."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import err


# --------------------------------------------------------------------------
# Common audit fields (PRD §2.4)
# --------------------------------------------------------------------------
def stamp_create(obj, full_audit=True):
    """Attach id, created_at, and (for full-audit entities) updated_at + version."""
    now = db.iso_now()
    obj["id"] = db.new_id()
    obj["created_at"] = now
    obj["_seq"] = db.next_seq()  # internal sort key, stripped on serialize
    if full_audit:
        obj["updated_at"] = now
        obj["version"] = 1
    return obj


def touch(obj):
    """Mutate audit fields: bump updated_at and version."""
    obj["updated_at"] = db.iso_now()
    obj["version"] = obj.get("version", 1) + 1


def serialize(obj):
    """Strip internal-only keys (those prefixed with '_')."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# Body parsing & field validation (priority 5 -> ERR_INVALID_REQUEST, 422)
# --------------------------------------------------------------------------
def get_json_body():
    if request.method in ("POST", "PUT", "PATCH"):
        body = request.get_json(silent=True)
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s below minimum %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s above maximum %s" % (field, maximum))
    return v


def require_number(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s below minimum %s" % (field, minimum))
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


# --------------------------------------------------------------------------
# Money / rounding (PRD §2.5)
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number half-up to a whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    """Ceiling integer division for non-negative numerator."""
    if denominator <= 0:
        return 0
    return -(-numerator // denominator)


# --------------------------------------------------------------------------
# Datetime parsing
# --------------------------------------------------------------------------
def parse_dt(value, field="datetime"):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0
# --------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


def sort_by_created(rows):
    return sorted(rows, key=lambda r: r["_seq"])

"""Shared helpers: timestamp formatting, common-field stamping, request parsing,
pagination, and half-up rounding.
"""
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db
from errors import err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Timestamps (PRD §2.4: ISO 8601 UTC, three fractional digits)
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 timestamp. Returns a tz-aware UTC datetime or raises
    ERR_INVALID_REQUEST on malformed input.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "expected ISO 8601 datetime string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "malformed datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_create(rec, with_version=True):
    now = db.now()
    rec["id"] = db.new_id()
    rec["created_at"] = now
    rec["_seq"] = db.next_seq()
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on any mutation (PRD §2.4)."""
    rec["updated_at"] = db.now()
    rec["version"] = rec.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Rounding (PRD §2.7: round half away from zero)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_apply(amount_cents, bps):
    """amount * bps / 10000, rounded half-up to whole cents (PRD §2.7)."""
    return round_half_up(Decimal(amount_cents) * Decimal(bps) / Decimal(10000))


def hours_floor(delta_seconds):
    """Whole hours, floored (PRD §3.5 etc.)."""
    return math.floor(delta_seconds / 3600)


# ---------------------------------------------------------------------------
# Request body / query parsing
# ---------------------------------------------------------------------------
def get_json():
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
        return data
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
    return body[field]


def require_int(body, field, minimum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, "%s must be >= %s" % (field, minimum))
    return val


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, "%s must be >= %s" % (field, minimum))
    return val


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, "%s must be a string" % field)
    return val


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------
def pagination_args():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows):
    """Sort by created_at ASC (tie-broken by insertion sequence) and slice."""
    limit, offset = pagination_args()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total

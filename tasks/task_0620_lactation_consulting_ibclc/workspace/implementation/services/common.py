"""Shared helpers: system fields, time parsing, rounding, pagination, validation
primitives."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import err, ERR_INVALID_REQUEST

# ----------------------------------------------------------------------------
# System fields (PRD §2.5)
# ----------------------------------------------------------------------------
# Full resources carry id, created_at, updated_at, version.
# Lightweight resources (FeedingAssessment, WeightedFeed) carry only id and
# created_at — no updated_at, no version.


def init_full(record):
    ts = db.now_iso_millis()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def init_lightweight(record):
    record["id"] = db.new_id()
    record["created_at"] = db.now_iso_millis()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mark a full resource as mutated: refresh updated_at, bump version
    (PRD §2.5)."""
    record["updated_at"] = db.now_iso_millis()
    record["version"] = record["version"] + 1


# ----------------------------------------------------------------------------
# Serialization — strip internal-only keys (those prefixed with _)
# ----------------------------------------------------------------------------


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------
# Rounding (PRD §2.8)
# ----------------------------------------------------------------------------


def round_half_up(numerator, denominator):
    """Round numerator/denominator half-up to the nearest integer. A value
    exactly halfway rounds to the larger magnitude (PRD §2.8)."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# Time parsing (PRD §2.4 — all timestamps ISO 8601 UTC)
# ----------------------------------------------------------------------------


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.
    Raises ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime value")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Malformed datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Body / field validation primitives
# ----------------------------------------------------------------------------


def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_str(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str) or v.strip() == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, min_value=None):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, min_value))
    return v


def optional_int(body, field, default, min_value=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, min_value))
    return v


def require_enum(body, field, choices):
    v = require_str(body, field)
    if v not in choices:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, choices))
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return v


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10 (1..100), offset default 0 (min 0)
# ----------------------------------------------------------------------------


def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        elif limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v


def paginate(records):
    """Sort by created_at ascending (PRD §2.3), apply limit/offset, return
    (page_serialized, limit, offset, total_count)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total

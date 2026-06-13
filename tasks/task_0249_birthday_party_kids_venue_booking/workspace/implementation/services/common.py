"""Shared helpers: timestamp parsing, field validation, pagination, common-field stamping."""

from datetime import datetime, timezone

from db import db, new_id, now_iso
from errors import err

# Entities carrying the full common-field set (id, created_at, updated_at, version).
# GuestParty and SystemClock are deliberately lighter (id + created_at only).


def stamp_create(record):
    """Attach common server-managed fields for a full-weight entity at create time."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_light_create(record):
    """Attach id + created_at only (GuestParty)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation bookkeeping: refresh updated_at and bump version by one."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def public_view(record):
    """Strip internal-only fields (those starting with _) for the response body."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------
# Request-shape validation (priority 5: ERR_INVALID_REQUEST, 422)
# ----------------------------------------------------------------------------

def require_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def as_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return value


def as_int(value, field):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def parse_iso8601(value, field):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ----------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit default 10, min 1, max 100; offset default 0
# ----------------------------------------------------------------------------

def parse_pagination():
    from flask import request

    def _parse_int(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer" % name)

    limit = _parse_int("limit", 10)
    offset = _parse_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation order (_seq), then window. Returns (page, total_count)."""
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total

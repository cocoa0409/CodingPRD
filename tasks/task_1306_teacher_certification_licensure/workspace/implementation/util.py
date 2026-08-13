"""Shared utilities: ids, timestamps, pagination, body validation helpers."""
import uuid
from datetime import datetime, timezone, timedelta

import errors
from db import db


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Current logical-clock time as ISO8601 UTC with three fractional digits."""
    return to_iso(db.now())


def to_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value, field="timestamp"):
    """Parse an ISO8601 datetime; accepts trailing Z. Returns aware datetime."""
    if not isinstance(value, str):
        raise errors.err_validation("%s must be an ISO8601 string" % field)
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise errors.err_validation("%s is not a valid ISO8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add calendar months to a datetime (used for 60-month license terms)."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


def touch(entity):
    """Bump updated_at and version on a mutated entity."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity):
    entity["created_at"] = iso_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    db.create_seq += 1
    entity["_seq"] = db.create_seq
    return entity


def get_body():
    from flask import request
    if not request.is_json:
        raise errors.err_validation("Request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise errors.err_validation("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err_validation("Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise errors.err_validation("Invalid value for %s" % field)
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise errors.err_validation("%s must be a boolean" % field)
    return value


def require_int(value, field, min_v=None, max_v=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.err_validation("%s must be an integer" % field)
    if min_v is not None and value < min_v:
        raise errors.err_validation("%s below minimum" % field)
    if max_v is not None and value > max_v:
        raise errors.err_validation("%s above maximum" % field)
    return value


def require_number(value, field, gt=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.err_validation("%s must be a number" % field)
    if gt is not None and not value > gt:
        raise errors.err_validation("%s must be > %s" % (field, gt))
    return value


def require_string(value, field):
    if not isinstance(value, str) or not value:
        raise errors.err_validation("%s must be a non-empty string" % field)
    return value


def paginate(items):
    """Apply limit/offset from query params per scaffold pagination defaults.
    Items must already be sorted (created_at ascending). Returns (page, limit, offset, total)."""
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err_validation("offset must be an integer")
        if offset < 0:
            raise errors.err_validation("offset must be >= 0")
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))

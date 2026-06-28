"""Shared parsing, validation, pagination, and datetime helpers."""
import math
from datetime import datetime, timezone, timedelta

import errors
from db import db


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Raises ERR_INVALID_REQUEST on bad input.
    """
    if not isinstance(value, str) or not value:
        raise errors.invalid_request("Invalid datetime value.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"Invalid ISO 8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add whole calendar months to a datetime, clamping day overflow."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to the last valid day of the target month
    day = dt.day
    # find max day in target month
    if month == 12:
        next_month_first = datetime(year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        next_month_first = datetime(year, month + 1, 1, tzinfo=dt.tzinfo)
    last_day = (next_month_first - timedelta(days=1)).day
    day = min(day, last_day)
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Request body / field validation
# ---------------------------------------------------------------------------
def get_json_body():
    from flask import request
    if request.method in ("POST", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object.")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not v.strip():
        raise errors.invalid_request(f"Field {name} must be a non-empty string.")
    return v


def opt_str(body, name, default=""):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {name} must be a string.")
    return v


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean.")
    return v


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean.")
    return v


def require_enum(body, name, choices):
    v = require_field(body, name)
    if v not in choices:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(choices)}.")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(records):
    return sorted(records, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Common system field stamping
# ---------------------------------------------------------------------------
def stamp_create(record):
    from db import iso_now_ms
    from clock import clock
    # created_at / updated_at use the LOGICAL clock so that time-driven tests
    # observe deterministic ordering tied to set_current_utc.
    ts = iso_now_ms(clock.now())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    from db import iso_now_ms
    from clock import clock
    record["updated_at"] = iso_now_ms(clock.now())
    record["version"] = record.get("version", 1) + 1
    return record

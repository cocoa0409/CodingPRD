"""Parsing / validation / formatting helpers."""
import re
from datetime import datetime, timezone

from flask import request

from errors import bad_input

_MISSING = object()
_POOL_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        raise bad_input("Field '%s' must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise bad_input("Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_input("Request body must be a JSON object")
    return data


def _require(data, name):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        raise bad_input("Missing required field '%s'" % name)
    return value


def req_str(data, name):
    value = _require(data, name)
    if not isinstance(value, str):
        raise bad_input("Field '%s' must be a string" % name)
    return value


def opt_str(data, name):
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise bad_input("Field '%s' must be a string" % name)
    return value


def req_int(data, name):
    value = _require(data, name)
    if isinstance(value, bool):
        raise bad_input("Field '%s' must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise bad_input("Field '%s' must be an integer" % name)


def req_num(data, name):
    value = _require(data, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_input("Field '%s' must be a number" % name)
    return value


def req_dt(data, name):
    return parse_dt(_require(data, name), name)


def req_enum(data, name, choices):
    value = _require(data, name)
    if not isinstance(value, str) or value not in choices:
        raise bad_input(
            "Field '%s' must be one of: %s" % (name, ", ".join(sorted(choices)))
        )
    return value


def parse_pool_month(value):
    if not isinstance(value, str) or not _POOL_MONTH_RE.match(value):
        raise bad_input("Field 'pool_month' must be in YYYY-MM format")
    year, month = int(value[:4]), int(value[5:7])
    if month < 1 or month > 12:
        raise bad_input("Field 'pool_month' must be in YYYY-MM format")
    return value


def pagination_params():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(str(raw_limit).strip())
        offset = int(str(raw_offset).strip())
    except (TypeError, ValueError):
        raise bad_input("Pagination parameters 'limit' and 'offset' must be integers")
    if limit < 1 or limit > 100:
        raise bad_input("Parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise bad_input("Parameter 'offset' must be non-negative")
    return limit, offset


def sort_and_paginate(records):
    """Default sort: created_at ascending (insertion order breaks ties)."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination

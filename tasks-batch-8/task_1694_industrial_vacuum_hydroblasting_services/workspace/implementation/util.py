"""Time, decimal, validation and serialization helpers."""

import re
import uuid
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import bad_request


# ---------------------------------------------------------------------------
# Time helpers — all domain time comes from the logical clock.
# ---------------------------------------------------------------------------

def now():
    """Current logical clock reading (timezone-aware UTC)."""
    return store.clock


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Clock display: seconds precision when whole, else millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def parse_datetime(value):
    """Parse an ISO 8601 datetime string; naive values are treated as UTC.

    Returns a timezone-aware UTC datetime, or None when unparseable.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a strict YYYY-MM-DD date string; returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Decimal helpers — money is integer cents, round-half-up everywhere.
# ---------------------------------------------------------------------------

def dec(value):
    """Coerce an int/float/str JSON number to Decimal without float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not a number")


def rhu(value, places):
    """Round half up to the given number of decimal places; returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole integer; returns int."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def num_out(value):
    """Render a stored Decimal/number for JSON output."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Request-shape validators (priority 3 -> ERR_INVALID_REQUEST / 400).
# ---------------------------------------------------------------------------

def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def get_body(required=True):
    """Fetch the JSON body. Returns {} when no body was sent.

    Malformed JSON is a 400. Non-object bodies are a 400.
    """
    from flask import request

    if not request.data:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON")
    if body is None:
        if required:
            raise bad_request("Request body is required")
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def req_field(body, field, kind="string", choices=None, min_value=None,
              gt_zero=False, gte_zero=False):
    """Validate a required field; returns the validated value."""
    if field not in body or body[field] is None:
        raise bad_request("Missing required field: %s" % field)
    value = body[field]
    return _check_value(field, value, kind, choices, min_value, gt_zero, gte_zero)


def opt_field(body, field, kind="string", choices=None, min_value=None,
              gt_zero=False, gte_zero=False, default=None):
    """Validate an optional field; returns the value or the default."""
    if field not in body or body[field] is None:
        return default
    value = body[field]
    return _check_value(field, value, kind, choices, min_value, gt_zero, gte_zero)


def _check_value(field, value, kind, choices, min_value, gt_zero, gte_zero):
    if kind == "string":
        if not isinstance(value, str):
            raise bad_request("Field %s must be a string" % field)
    elif kind == "bool":
        if not isinstance(value, bool):
            raise bad_request("Field %s must be a boolean" % field)
    elif kind == "int":
        if not is_int(value):
            raise bad_request("Field %s must be an integer" % field)
    elif kind == "number":
        if not is_num(value):
            raise bad_request("Field %s must be a number" % field)
        value = dec(value)
    elif kind == "datetime":
        parsed = parse_datetime(value)
        if parsed is None:
            raise bad_request("Field %s must be an ISO 8601 datetime" % field)
        value = parsed
    elif kind == "date":
        parsed = parse_date(value)
        if parsed is None:
            raise bad_request("Field %s must be a YYYY-MM-DD date" % field)
        value = parsed
    elif kind == "array":
        if not isinstance(value, list):
            raise bad_request("Field %s must be an array" % field)
    if choices is not None:
        if kind == "array":
            for item in value:
                if item not in choices:
                    raise bad_request("Field %s contains an invalid value" % field)
        elif value not in choices:
            raise bad_request("Field %s must be one of %s" % (field, ", ".join(choices)))
    if gt_zero and not value > 0:
        raise bad_request("Field %s must be greater than zero" % field)
    if gte_zero and not value >= 0:
        raise bad_request("Field %s must be zero or greater" % field)
    if min_value is not None and not value >= min_value:
        raise bad_request("Field %s is below its minimum" % field)
    return value


# ---------------------------------------------------------------------------
# Entity helpers.
# ---------------------------------------------------------------------------

def mint_id():
    return str(uuid.uuid4())


def new_entity(collection, fields):
    """Create an entity dict with the four common system-managed fields."""
    ts = now()
    entity = dict(fields)
    entity["id"] = mint_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    collection[entity["id"]] = entity
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version by one."""
    entity["updated_at"] = now()
    entity["version"] += 1


def serialize(obj):
    """Deep-convert an entity for JSON output: datetimes and Decimals out."""
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    if isinstance(obj, datetime):
        return fmt_ts(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def list_paginated(collection, filters, args):
    """Filter, sort by created_at ascending, and paginate a collection.

    Returns (page_items, limit, offset, total_count).
    """
    items = [e for e in collection.values()
             if all(e.get(k) == v for k, v in filters.items())]
    items.sort(key=lambda e: e["created_at"])  # stable: ties keep insertion order

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit, 10) if isinstance(raw_limit, str) else None
        except ValueError:
            limit = None
        if limit is None or limit < 1 or limit > 100:
            raise bad_request("limit must be an integer between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset, 10) if isinstance(raw_offset, str) else None
        except ValueError:
            offset = None
        if offset is None or offset < 0:
            raise bad_request("offset must be a non-negative integer")

    total = len(items)
    return items[offset:offset + limit], limit, offset, total

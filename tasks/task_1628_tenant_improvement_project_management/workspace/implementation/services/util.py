"""Shared helpers: ID minting, timestamps, pagination, type validation."""

import re
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import invalid_request


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return store.now()


def parse_iso8601(s):
    """Parse an ISO8601 datetime string. Returns datetime in UTC.

    Accepts both 'Z' and '+00:00' suffixes; also accepts date-only strings
    which are treated as UTC midnight.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    s = s.strip()
    # date-only
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    # datetime with Z
    s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_z(dt):
    """Render a datetime as ISO8601 with Z suffix and 3 fractional digits."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_clock_dt():
    return parse_iso8601(store.logical_clock)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


def round_half_up_cents(dec_value):
    """Round a Decimal to whole cents (integer) using ROUND_HALF_UP."""
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_pagination_params():
    """Read limit/offset from query string with validation."""
    from flask import request
    limit_s = request.args.get("limit", "10")
    offset_s = request.args.get("offset", "0")
    try:
        limit = int(limit_s)
    except (ValueError, TypeError):
        raise invalid_request("limit must be an integer")
    try:
        offset = int(offset_s)
    except (ValueError, TypeError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending, then apply pagination window."""
    items_sorted = sorted(items, key=lambda x: x["created_at"])
    total = len(items_sorted)
    page = items_sorted[offset : offset + limit]
    return page, total


def require_fields(body, fields):
    """Check that all required fields are present in body."""
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    for f in fields:
        if f not in body:
            raise invalid_request(f"Missing required field: {f}")


def optional_field(body, field, default=None):
    return body.get(field, default)


def bump_version(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def make_common_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }

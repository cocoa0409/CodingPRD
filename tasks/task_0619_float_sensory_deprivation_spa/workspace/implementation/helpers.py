"""Shared parsing / validation / pagination helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


def get_json_body():
    """Return the request body as a dict, or {} when absent. Reject malformed JSON."""
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            data = request.get_json(silent=True, force=True)
        except Exception:
            raise errors.invalid_request("Body is not valid JSON.")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Body must be a JSON object.")
        return data
    return {}


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime to an aware UTC datetime. Raise on failure."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field} must be an ISO 8601 string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"{field} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def round_half_up(value):
    """Round a Decimal to the nearest integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- pagination
def parse_pagination():
    """Parse limit/offset query params per PRD §2.3 (default 10, min 1, max 100; offset default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = 10
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    offset = 0
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (stable via _seq), slice, return (page, meta)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta

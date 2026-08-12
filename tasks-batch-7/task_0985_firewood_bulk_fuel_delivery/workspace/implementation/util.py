"""Shared helpers: serialization, common fields, pagination, decimal math."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


def now_iso():
    """Timestamp string for created_at/updated_at: ISO 8601 UTC, 3 fractional digits.

    These are record timestamps — they use wall clock for uniqueness ordering,
    while business logic uses the logical clock (clock.clock).
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def dec(x):
    """Coerce to Decimal safely."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_half_up_int(x):
    """Round to integer cents, half-up."""
    return int(dec(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_3dp(x):
    """Round to 3 decimal places, half-up (cord-equivalent line-level precision)."""
    return float(dec(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def get_json_body():
    """Parse request JSON body; missing/invalid JSON -> ERR_VALIDATION."""
    if not request.is_json:
        raise errors.validation("Request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.validation(f"Missing required field: {name}")
    return body[name]


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field {name} must be an integer")
    return v


def require_number(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.validation(f"Field {name} must be a number")
    return v


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"Field {name} must be a non-empty string")
    return v


def parse_pagination():
    """Parse limit/offset per PRD §2.3: limit default 10, min 1, max 100; offset default 0."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit out of range")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending, then slice."""
    items_sorted = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(items_sorted)
    return items_sorted[offset:offset + limit], total


def base_resource(entity_id, created_at, updated_at, version):
    return {
        "id": entity_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }


def touch(entity):
    """Bump updated_at and version on a common-fields entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1

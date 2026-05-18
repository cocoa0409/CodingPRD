"""Response envelope helpers."""

import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import APIError


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _utc_now_iso() -> str:
    # ISO 8601 UTC with three fractional digits and trailing Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _serialize(value):
    if isinstance(value, Decimal):
        # Render as number; quantize to 2 dp where applicable preserved by callers
        # Keep as float in JSON (Flask JSON encoder handles)
        # Avoid scientific notation
        s = format(value, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        try:
            # If integral, return as int
            if "." not in s:
                return int(s)
            return float(s)
        except Exception:
            return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


def success(data, status_code: int = 200, pagination: dict = None):
    response_type = "array" if isinstance(data, list) else "object"
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _utc_now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    payload = {
        "meta": meta,
        "response_type": response_type,
        "data": _serialize(data) if data is not None else {},
    }
    return jsonify(payload), status_code


def error_response(err: APIError):
    payload = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _utc_now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(payload), err.http_status


def parse_pagination(args):
    """Parse and validate pagination params from a flask request.args MultiDict."""
    try:
        limit = int(args.get("limit", PAGINATION_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        from errors import raise_error
        raise_error("ERR_VALIDATION_FAILED", "limit must be an integer")
    try:
        offset = int(args.get("offset", PAGINATION_DEFAULT_OFFSET))
    except (TypeError, ValueError):
        from errors import raise_error
        raise_error("ERR_VALIDATION_FAILED", "offset must be an integer")

    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        from errors import raise_error
        raise_error(
            "ERR_VALIDATION_FAILED",
            f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}",
        )
    if offset < 0:
        from errors import raise_error
        raise_error("ERR_VALIDATION_FAILED", "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset : offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }

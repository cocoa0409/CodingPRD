"""Request-body and pagination validation helpers (PRD §2.3, §2.5, §2.9)."""
from datetime import datetime, timezone

from flask import request

import errors

SERVICE_TYPES = {"TOW", "JUMP", "LOCKOUT", "FUEL", "TIRE"}


def parse_datetime(value, name):
    """Parse an ISO 8601 datetime string -> tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive values are treated as UTC.
    Raises ERR_INVALID_REQUEST on a malformed value.
    """
    if not isinstance(value, str):
        raise errors.invalid_request(f"{name} must be an ISO 8601 datetime string.")
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.invalid_request(f"{name} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_body():
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST if malformed.

    A missing body is treated as an empty object (lifecycle endpoints take no body).
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def parse_pagination():
    """Read limit/offset query params. Raise ERR_INVALID_PAGINATION on violation.

    limit: default 10, 1..100. offset: default 0, >= 0.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_pagination("limit must be in 1..100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_pagination("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_pagination("offset must be >= 0.")

    return limit, offset


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_present(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise errors.invalid_request(f"Missing required field: {f}.")


def require_lat(value, name="latitude"):
    if not is_number(value) or value < -90 or value > 90:
        raise errors.invalid_request(f"{name} must be a number in -90..90.")


def require_lng(value, name="longitude"):
    if not is_number(value) or value < -180 or value > 180:
        raise errors.invalid_request(f"{name} must be a number in -180..180.")


def require_str(value, name):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request(f"{name} must be a non-empty string.")


def require_enum(value, allowed, name):
    if value not in allowed:
        raise errors.invalid_request(f"{name} must be one of {sorted(allowed)}.")

"""Parsing, validation, and pagination helpers (PRD 2.3 / validation priority 6)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None or not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
        return data
    return {}


def req(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return data[field]


def as_str(v, field, min_len=None):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    if min_len is not None and len(v) < min_len:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {field} must be at least {min_len} characters",
        )
    return v


def req_str(data, field, min_len=None):
    return as_str(req(data, field), field, min_len)


def opt_str(data, field, min_len=None):
    if field not in data or data[field] is None:
        return None
    return as_str(data[field], field, min_len)


def as_enum(v, field, choices):
    if v not in choices:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {field} must be one of {sorted(choices)}",
        )
    return v


def req_enum(data, field, choices):
    return as_enum(req(data, field), field, choices)


def opt_enum(data, field, choices):
    if field not in data or data[field] is None:
        return None
    return as_enum(data[field], field, choices)


def as_int(v, field, minimum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be >= {minimum}")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a boolean")
    return v


def as_str_list(v, field):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an array of strings"
        )
    return v


def as_dt(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    try:
        return parse_dt(v)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"Field {field} must be an ISO 8601 timestamp"
        )


def req_dt(data, field):
    return as_dt(req(data, field), field)


def as_checksum(v, field="checksum"):
    if not isinstance(v, str) or not CHECKSUM_RE.match(v):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Field checksum must be 64 lowercase hexadecimal characters",
        )
    return v


def as_occ_version(v, field="expected_case_version"):
    """OCC field: accept integer or decimal-string representations."""
    if isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be an integer")


def pagination_args():
    """limit/offset query parameters (defaults 10/0; limit in [1, 100])."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset

"""Request-payload validation helpers and pagination parsing."""
import math

from flask import request

from db import _parse_iso
from errors import ApiError, ERR_INVALID_REQUEST


def body():
    """Return the JSON request body as a dict ({} for empty). Reject non-objects."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _is_bool(v):
    return isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing or invalid field: {field}")
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Invalid field: {field}")
    return v


def req_int(data, field, positive=False):
    v = data.get(field)
    if _is_bool(v) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field must be a positive integer: {field}")
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Invalid enum value for field: {field}")
    return v


def req_dt(data, field):
    """Parse a required ISO-8601 datetime field. Returns an aware UTC datetime."""
    v = data.get(field)
    dt = _parse_iso(v)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Invalid ISO8601 datetime: {field}")
    return dt


def pagination():
    """Parse limit/offset query params per §2.3 (default 10, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def ceil_div_seconds(a, b, unit_seconds):
    """Ceil of (a - b) expressed in units of unit_seconds. a, b are datetimes."""
    delta = (a - b).total_seconds()
    if delta <= 0:
        return 0
    return math.ceil(delta / unit_seconds)

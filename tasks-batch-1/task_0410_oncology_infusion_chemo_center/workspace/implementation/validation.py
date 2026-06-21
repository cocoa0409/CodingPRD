"""Input parsing and validation helpers (body well-formedness, pagination, datetimes)."""
import re
from datetime import datetime, date

from flask import request

import errors
from errors import err

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    """Return the JSON body as a dict; tolerate empty bodies for action endpoints."""
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        # Empty / unparseable body -> treat as empty dict (action endpoints take no body)
        return {}
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_str(body, field, allow_empty=False):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    if not allow_empty and val.strip() == "":
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must not be empty" % field)
    return val


def require_number(body, field, gt=None, ge=None, le=None, lt=None):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return _check_number(body[field], field, gt, ge, le, lt)


def optional_number(body, field, default=None, gt=None, ge=None, le=None, lt=None):
    if field not in body or body[field] is None:
        return default
    return _check_number(body[field], field, gt, ge, le, lt)


def _check_number(val, field, gt, ge, le, lt):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    if gt is not None and not (val > gt):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be > %s" % (field, gt))
    if ge is not None and not (val >= ge):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, ge))
    if le is not None and not (val <= le):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be <= %s" % (field, le))
    if lt is not None and not (val < lt):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be < %s" % (field, lt))
    return val


def require_int(body, field, ge=None, le=None, gt=None):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return _check_int(body[field], field, ge, le, gt)


def optional_int(body, field, default=None, ge=None, le=None, gt=None):
    if field not in body or body[field] is None:
        return default
    return _check_int(body[field], field, ge, le, gt)


def _check_int(val, field, ge, le, gt):
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if ge is not None and not (val >= ge):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, ge))
    if gt is not None and not (val > gt):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be > %s" % (field, gt))
    if le is not None and not (val <= le):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be <= %s" % (field, le))
    return val


def require_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return val


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def require_date(body, field):
    val = require_str(body, field)
    if not _DATE_RE.match(val):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO date YYYY-MM-DD" % field)
    try:
        date.fromisoformat(val)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s is not a valid calendar date" % field)
    return val


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime; return a timezone-aware datetime for comparison."""
    if not isinstance(value, str):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s == "":
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must not be empty" % field)
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 datetime" % field)
    return dt


def require_datetime(body, field):
    if field not in body or body[field] is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return parse_datetime(body[field], field)


def get_pagination():
    """Parse limit/offset query params with defaults and bounds (limit 1..100 default 10, offset >= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted by created_at asc; return the window slice."""
    return items[offset:offset + limit]

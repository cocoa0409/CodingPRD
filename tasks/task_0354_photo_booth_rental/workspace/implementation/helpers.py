"""Shared request-parsing / validation / pagination helpers.

PRD §2.9: well-formedness failures (missing required field, bad enum,
out-of-range number, event_end <= event_start) all surface as
ERR_INVALID_REQUEST (422). There is no separate missing-field error in this
scaffold's catalogue.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import errors
from errors import err

_MISSING = object()


def get_json():
    """Return the parsed JSON body (or {} if none/empty). A structurally
    malformed body is treated as an invalid request."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # Non-empty but unparseable body.
        if request.data and request.data.strip():
            raise err(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
        return {}
    if not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_field(body, name):
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return val


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % name)
    return val


def optional_string(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a string." % name)
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s." % (name, minimum))
    if maximum is not None and val > maximum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be <= %s." % (name, maximum))
    return val


def optional_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s." % (name, minimum))
    if maximum is not None and val > maximum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be <= %s." % (name, maximum))
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a string." % name)
    if val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s." % (name, sorted(allowed)))
    return val


def optional_enum(body, name, allowed, default):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s." % (name, sorted(allowed)))
    return val


def require_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean." % name)
    return val


def _coerce_decimal(val, name, max_dp=None):
    """Accept int/float/str -> Decimal. Money inputs allow at most max_dp
    decimal places (PRD §2.5)."""
    if isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a number." % name)
    if isinstance(val, (int, float)):
        d = Decimal(str(val))
    elif isinstance(val, str):
        try:
            d = Decimal(val)
        except (InvalidOperation, ValueError):
            raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a number." % name)
    else:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a number." % name)
    if max_dp is not None:
        exp = d.normalize().as_tuple().exponent
        if isinstance(exp, int) and exp < -max_dp:
            raise err(errors.ERR_INVALID_REQUEST,
                      "Field %s must have at most %d decimal places." % (name, max_dp))
    return d


def require_money(body, name, minimum=None, strictly_positive=False):
    """Required money field with at most 2 decimal places (PRD §2.5)."""
    val = require_field(body, name)
    d = _coerce_decimal(val, name, max_dp=2)
    if strictly_positive and d <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be > 0." % name)
    if minimum is not None and d < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s." % (name, minimum))
    return d


def parse_datetime(body, name):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO-8601 string." % name)
    dt = parse_iso(val)
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s is not a valid ISO-8601 datetime." % name)
    return dt


def parse_optional_datetime(body, name):
    if name not in body or body.get(name) is None:
        return None
    val = body.get(name)
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO-8601 string." % name)
    dt = parse_iso(val)
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s is not a valid ISO-8601 datetime." % name)
    return dt


def parse_iso(s):
    raw = s
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    # Normalise to timezone-aware UTC for consistent arithmetic.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def pagination_params():
    """PRD §2.3: limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
    try:
        offset = int(offset) if offset is not None else 0
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (tie-break by creation seq) then slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total

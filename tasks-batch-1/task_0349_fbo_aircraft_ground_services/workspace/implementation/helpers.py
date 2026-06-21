"""Shared request-parsing / validation / pagination helpers."""
from datetime import datetime

from flask import request

import errors
from errors import err

_MISSING = object()


def get_json():
    """Return the parsed JSON body (or {} if none/empty). A structurally
    malformed body is an absent/malformed field situation."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(errors.ERR_MISSING_FIELD, "Request body must be a JSON object.")
    return body


def require_field(body, name):
    """PRD §2.5: a required field that is entirely absent or structurally
    malformed (None) -> ERR_MISSING_FIELD (400)."""
    val = body.get(name, _MISSING)
    if val is _MISSING or val is None:
        raise err(errors.ERR_MISSING_FIELD, "Missing required field: %s" % name)
    return val


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_MISSING_FIELD, "Field %s must be a non-empty string." % name)
    return val


def require_int(body, name, minimum=None):
    """Required integer field. Absent/malformed -> ERR_MISSING_FIELD (400);
    present-but-out-of-range -> ERR_VALIDATION (422) (PRD §2.5)."""
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_MISSING_FIELD, "Field %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_VALIDATION, "Field %s must be >= %s." % (name, minimum))
    return val


def optional_int(body, name, default, minimum=None):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_MISSING_FIELD, "Field %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_VALIDATION, "Field %s must be >= %s." % (name, minimum))
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise err(errors.ERR_MISSING_FIELD, "Field %s must be a string." % name)
    if val not in allowed:
        raise err(errors.ERR_VALIDATION, "Field %s must be one of %s." % (name, sorted(allowed)))
    return val


def require_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if not isinstance(val, bool):
        raise err(errors.ERR_VALIDATION, "Field %s must be a boolean." % name)
    return val


def parse_datetime(body, name):
    """Required ISO-8601 datetime field. Absent/malformed -> ERR_MISSING_FIELD."""
    val = require_field(body, name)
    if not isinstance(val, str):
        raise err(errors.ERR_MISSING_FIELD, "Field %s must be an ISO-8601 string." % name)
    dt = _parse_iso(val)
    if dt is None:
        raise err(errors.ERR_MISSING_FIELD, "Field %s is not a valid ISO-8601 datetime." % name)
    return dt


def parse_optional_datetime(body, name):
    if name not in body or body.get(name) is None:
        return None
    val = body.get(name)
    if not isinstance(val, str):
        raise err(errors.ERR_MISSING_FIELD, "Field %s must be an ISO-8601 string." % name)
    dt = _parse_iso(val)
    if dt is None:
        raise err(errors.ERR_MISSING_FIELD, "Field %s is not a valid ISO-8601 datetime." % name)
    return dt


def _parse_iso(s):
    raw = s
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def pagination_params():
    """PRD §2.3: limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (ValueError, TypeError):
        raise err(errors.ERR_VALIDATION, "limit must be an integer.")
    try:
        offset = int(offset) if offset is not None else 0
    except (ValueError, TypeError):
        raise err(errors.ERR_VALIDATION, "offset must be an integer.")
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

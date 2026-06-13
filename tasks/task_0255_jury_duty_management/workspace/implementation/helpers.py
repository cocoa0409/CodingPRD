"""Shared request-parsing, validation, and pagination helpers.

Validation priority (PRD §4, scaffold §1.4): auth -> existence -> state ->
business/temporal -> OCC -> request-body validation (ERR_INVALID_REQUEST, 422)
is LAST. So body-shape validation must be performed only after existence/state/
business checks have passed at each endpoint.
"""
from datetime import datetime, timezone

from flask import request

import errors


# ---------------------------------------------------------------------------
# Body access
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON body as a dict (empty dict when no/blank body).

    A malformed JSON body is treated as an invalid request only when the
    endpoint actually needs fields out of it; endpoints that take no input
    tolerate an empty or missing body.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Field validation primitives (all raise ERR_INVALID_REQUEST / 422)
# ---------------------------------------------------------------------------

def _invalid(msg):
    return errors.err("ERR_INVALID_REQUEST", msg)


def require_present(body, field):
    if field not in body or body[field] is None:
        raise _invalid("Missing required field: %s" % field)
    return body[field]


def require_string(body, field):
    v = require_present(body, field)
    if not isinstance(v, str) or v == "":
        raise _invalid("Field %s must be a non-empty string" % field)
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_int(body, field, minimum=None, maximum=None):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _invalid("Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise _invalid("Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise _invalid("Field %s must be <= %s" % (field, maximum))
    return v


def require_number(body, field, minimum=None, maximum=None, gt=None):
    v = require_present(body, field)
    if not _is_number(v):
        raise _invalid("Field %s must be a number" % field)
    v = float(v)
    if minimum is not None and v < minimum:
        raise _invalid("Field %s must be >= %s" % (field, minimum))
    if gt is not None and not v > gt:
        raise _invalid("Field %s must be > %s" % (field, gt))
    if maximum is not None and v > maximum:
        raise _invalid("Field %s must be <= %s" % (field, maximum))
    return v


def require_bool(body, field):
    v = require_present(body, field)
    if not isinstance(v, bool):
        raise _invalid("Field %s must be a boolean" % field)
    return v


def require_enum(body, field, allowed):
    v = require_present(body, field)
    if v not in allowed:
        raise _invalid("Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def optional_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------

def parse_iso8601(value, field):
    """Parse an ISO 8601 datetime string to a tz-aware UTC datetime.

    Accepts a trailing 'Z'. Raises ERR_INVALID_REQUEST when unparseable.
    """
    if not isinstance(value, str) or not value:
        raise _invalid("Field %s must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise _invalid("Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def calendar_date(dt):
    """Return the calendar date (date object) of a tz-aware UTC datetime."""
    return dt.date()


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3 / scaffold §1.0)
#   limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def pagination_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise _invalid("limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        if limit_v > 100:
            limit_v = 100

    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise _invalid("offset must be an integer")
        if offset_v < 0:
            offset_v = 0

    return limit_v, offset_v


def paginate(rows, serialize):
    """Sort by created_at ASC (insertion-seq tie-break), paginate, and wrap.

    `rows` is a list of stored entity dicts; `serialize` projects each to its
    response shape. Returns (data_list, pagination_meta).
    """
    limit, offset = pagination_params()
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    data = [serialize(r) for r in page]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return data, meta

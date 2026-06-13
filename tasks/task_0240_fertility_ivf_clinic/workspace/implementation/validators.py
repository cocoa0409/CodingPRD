"""Reusable payload validation + parsing helpers (ERR_VALIDATION, PRD §2.6)."""

import re
from datetime import datetime, timezone

import errors as E
from errors import fail

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$"
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require(body, field):
    if field not in body or body[field] is None:
        fail(E.ERR_VALIDATION, "Missing required field: %s" % field)
    return body[field]


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        fail(E.ERR_VALIDATION, "%s must be a string" % field)
    return v


def req_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or not v.strip():
        fail(E.ERR_VALIDATION, "%s must be a non-empty string" % field)
    return v


def req_int(body, field, min_value=None, max_value=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        fail(E.ERR_VALIDATION, "%s must be an integer" % field)
    if min_value is not None and v < min_value:
        fail(E.ERR_VALIDATION, "%s must be >= %s" % (field, min_value))
    if max_value is not None and v > max_value:
        fail(E.ERR_VALIDATION, "%s must be <= %s" % (field, max_value))
    return v


def opt_int(body, field, default=None, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, min_value=min_value, max_value=max_value)


def req_number(body, field, min_value=None, max_value=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(E.ERR_VALIDATION, "%s must be a number" % field)
    if min_value is not None and v < min_value:
        fail(E.ERR_VALIDATION, "%s must be >= %s" % (field, min_value))
    if max_value is not None and v > max_value:
        fail(E.ERR_VALIDATION, "%s must be <= %s" % (field, max_value))
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        fail(E.ERR_VALIDATION, "%s must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        fail(E.ERR_VALIDATION, "%s must be one of %s" % (field, sorted(allowed)))
    return v


def req_datetime(body, field):
    v = require(body, field)
    if not isinstance(v, str) or not _ISO_RE.match(v):
        fail(E.ERR_VALIDATION, "%s must be an ISO 8601 datetime" % field)
    return v


def opt_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_datetime(body, field)


def req_datetime_or_date(body, field):
    """date_of_birth may be a bare ISO date (YYYY-MM-DD) or a full datetime."""
    v = require(body, field)
    if not isinstance(v, str) or not (_ISO_DATE_RE.match(v) or _ISO_RE.match(v)):
        fail(E.ERR_VALIDATION, "%s must be an ISO date or datetime" % field)
    return v


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime for comparison."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

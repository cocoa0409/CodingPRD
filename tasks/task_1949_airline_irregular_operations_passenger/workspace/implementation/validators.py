"""Request-shape validation helpers: JSON body parsing, field type checks,
enum membership, datetime parsing, pagination parameter parsing."""

import re
from datetime import datetime, timezone

import errors
from flask import request


def get_json_body():
    """Parse the request JSON body. Missing/invalid JSON -> ERR_INVALID_REQUEST."""
    if not request.is_json:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Request body must be JSON")
    try:
        body = request.get_json()
    except Exception:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Request body is not parseable JSON")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def get_json_body_optional():
    """Like get_json_body, but a wholly absent body (no content-type) yields {}."""
    if not request.data:
        return {}
    return get_json_body()


def require_field(body, name):
    if name not in body or body[name] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return body[name]


def req_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


def opt_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


def req_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return v


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name)


def req_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def req_enum(body, name, domain):
    v = require_field(body, name)
    if not isinstance(v, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    if v not in domain:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "Field %s value %r is not a member of the declared enum domain" % (name, v))
    return v


def opt_enum(body, name, domain, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, domain)


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(value, field_name):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str) or not _ISO_RE.match(value):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field %s must be an ISO 8601 datetime string" % field_name)
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field %s must be an ISO 8601 datetime string" % field_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, name):
    return parse_datetime(require_field(body, name), name)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field %s must be an ISO date string (YYYY-MM-DD)" % name)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field %s must be an ISO date string (YYYY-MM-DD)" % name)
    return v


def pagination_params():
    """Parse limit/offset query params with scaffold defaults: limit default 10,
    min 1, max 100; offset default 0, min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def opt_query_enum(name, domain):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in domain:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "Query parameter %s value %r is not in the declared enum domain" % (name, v))
    return v

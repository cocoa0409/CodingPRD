"""Shared helpers: timestamps, ids, entity lifecycle, request validation."""

import random
import string
import uuid
from datetime import datetime, timezone

from flask import request

from db import clock
from errors import ApiError


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field '%s' must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Ids / entity lifecycle
# ---------------------------------------------------------------------------

def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_entity():
    now = clock.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = clock.now()


# ---------------------------------------------------------------------------
# Request body / field validation (priority 4 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def require_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return body


def optional_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def field_str(body, name, required=False, default=None):
    v = body.get(name)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field '%s'" % name)
        return default
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be a string" % name)
    return v


def field_int(body, name, required=False, default=None, minimum=None, maximum=None):
    v = body.get(name)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field '%s'" % name)
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be an integer" % name)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field '%s' must be >= %d" % (name, minimum))
    if maximum is not None and v > maximum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field '%s' must be <= %d" % (name, maximum))
    return v


def field_bool(body, name, required=False, default=None):
    v = body.get(name)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field '%s'" % name)
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be a boolean" % name)
    return v


def field_enum(body, name, values, required=False, default=None):
    v = body.get(name)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field '%s'" % name)
        return default
    if not isinstance(v, str) or v not in values:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field '%s' must be one of %s" % (name, ", ".join(values)))
    return v


def field_enum_list(body, name, values, required=False, default=None):
    v = body.get(name)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field '%s'" % name)
        return default
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be an array" % name)
    for item in v:
        if not isinstance(item, str) or item not in values:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "field '%s' items must be one of %s" % (name, ", ".join(values)))
    return v


def field_dt(body, name, required=False, default=None):
    v = body.get(name)
    if v is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field '%s'" % name)
        return default
    return parse_dt(v, name)


# ---------------------------------------------------------------------------
# Pagination (limit / offset)
# ---------------------------------------------------------------------------

def pagination_args():
    raw_limit = request.args.get("limit")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit, 10)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset, 10)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def bool_filter_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("true", "1"):
        return True
    if v in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", 400, "query parameter '%s' must be a boolean" % name)

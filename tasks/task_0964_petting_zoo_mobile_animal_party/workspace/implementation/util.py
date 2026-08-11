"""Shared helpers: logical clock, timestamps, body validation, pagination."""
import math
import uuid
from datetime import datetime, timezone

from flask import request

from db import store
from errors import ApiError, raise_err, ERR_INVALID_REQUEST


def now():
    """The server's logical clock. Every temporal rule evaluates against this."""
    return store.clock


def wall_now():
    """Wall-clock time, used only for created_at/updated_at/request timestamps."""
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Request body validation (ERR_INVALID_REQUEST on any violation)
# ---------------------------------------------------------------------------

def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _present(body, key):
    return key in body and body[key] is not None


def v_str(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % key)
        return default
    if not isinstance(body[key], str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a string" % key)
    return body[key]


def v_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        if required:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % key)
        return default
    val = body[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % key)
    if minimum is not None and val < minimum:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is below its minimum" % key)
    if maximum is not None and val > maximum:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is above its maximum" % key)
    return val


def v_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % key)
        return default
    if not isinstance(body[key], bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a boolean" % key)
    return body[key]


def v_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % key)
        return default
    if not isinstance(body[key], str) or body[key] not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (key, sorted(allowed)))
    return body[key]


def v_dt(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % key)
        return default
    return parse_dt(body[key], key)


def v_str_array(body, key, allowed=None, required=True, default=None):
    if not _present(body, key):
        if required:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % key)
        return default
    val = body[key]
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an array of strings" % key)
    if allowed is not None:
        for x in val:
            if x not in allowed:
                raise_err(ERR_INVALID_REQUEST, "Field '%s' contains an invalid value" % key)
    return val


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def new_common():
    ts = wall_now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def new_immutable():
    return {"id": new_id(), "created_at": wall_now()}


def bump(entity):
    """Versioned mutation: version += 1 and updated_at refreshes in the same write."""
    entity["version"] += 1
    entity["updated_at"] = wall_now()


def touch_immutable_ok(entity):
    entity["updated_at"] = wall_now()


# ---------------------------------------------------------------------------
# Pagination (limit/offset, defaults 10/0, limit clamped to [1, 100])
# ---------------------------------------------------------------------------

def pagination_args():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, serializer):
    """items: full filtered collection. Returns (page_data, pagination_meta)."""
    limit, offset = pagination_args()
    ordered = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [serializer(x) for x in page], meta

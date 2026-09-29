"""Request parsing, schema and numeric-domain validation.

Priority 3 (body schema) and priority 4 (enum / numeric domain) of the
evaluation ladder in PRD section 2.11.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

BAD = "ERR_INVALID_REQUEST"


def bad(msg):
    raise ApiError(BAD, msg)


# ----------------------------------------------------------------- body parsing
def body(required=(), optional=()):
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        payload = {}
    else:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            bad("The request body is not valid JSON.")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        bad("The request body must be a JSON object.")
    allowed = set(required) | set(optional)
    unknown = [k for k in payload.keys() if k not in allowed]
    if unknown:
        bad("Unknown field(s): %s." % ", ".join(sorted(unknown)))
    missing = [k for k in required if k not in payload]
    if missing:
        bad("Missing required field(s): %s." % ", ".join(missing))
    return payload


def no_body():
    return body()


# ----------------------------------------------------------------- type helpers
def as_string(payload, name, nullable=False, min_len=None, max_len=None):
    v = payload.get(name)
    if v is None:
        if nullable and name in payload:
            return None
        if name in payload:
            bad("Field %r must be a string." % name)
        return None
    if not isinstance(v, str):
        bad("Field %r must be a string." % name)
    if min_len is not None and len(v) < min_len:
        bad("Field %r is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(v) > max_len:
        bad("Field %r is longer than %d characters." % (name, max_len))
    return v


def as_bool(payload, name, default=None):
    if name not in payload:
        return default
    v = payload[name]
    if not isinstance(v, bool):
        bad("Field %r must be a boolean." % name)
    return v


def as_int(payload, name, minimum=None, maximum=None, nullable=False, default=None):
    if name not in payload:
        return default
    v = payload[name]
    if v is None:
        if nullable:
            return None
        bad("Field %r must be an integer." % name)
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field %r must be an integer." % name)
    if minimum is not None and v < minimum:
        bad("Field %r must be at least %s." % (name, minimum))
    if maximum is not None and v > maximum:
        bad("Field %r must be at most %s." % (name, maximum))
    return v


def as_number(payload, name, minimum=None, maximum=None, nullable=False,
              default=None, exclusive_min=None):
    if name not in payload:
        return default
    v = payload[name]
    if v is None:
        if nullable:
            return None
        bad("Field %r must be a number." % name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("Field %r must be a number." % name)
    d = Decimal(str(v))
    if exclusive_min is not None and d <= Decimal(str(exclusive_min)):
        bad("Field %r must be greater than %s." % (name, exclusive_min))
    if minimum is not None and d < Decimal(str(minimum)):
        bad("Field %r must be at least %s." % (name, minimum))
    if maximum is not None and d > Decimal(str(maximum)):
        bad("Field %r must be at most %s." % (name, maximum))
    return v


def as_enum(payload, name, allowed, nullable=False, default=None):
    if name not in payload:
        return default
    v = payload[name]
    if v is None:
        if nullable:
            return None
        bad("Field %r must be one of %s." % (name, ", ".join(allowed)))
    if not isinstance(v, str) or v not in allowed:
        bad("Field %r must be one of %s." % (name, ", ".join(allowed)))
    return v


def as_id(payload, name, nullable=False):
    if name not in payload:
        return None
    v = payload[name]
    if v is None:
        if nullable:
            return None
        bad("Field %r must be a string identifier." % name)
    if not isinstance(v, str) or v == "":
        bad("Field %r must be a string identifier." % name)
    return v


def as_datetime(payload, name):
    v = payload.get(name)
    if not isinstance(v, str):
        bad("Field %r must be an ISO 8601 datetime string." % name)
    return parse_datetime(v, name)


def parse_datetime(text, name="datetime"):
    if not isinstance(text, str):
        bad("Field %r must be an ISO 8601 datetime string." % name)
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except Exception:
        bad("Field %r is not a valid ISO 8601 datetime." % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    if name not in request.args:
        return None
    v = request.args.get(name)
    if v not in allowed:
        bad("Query parameter %r must be one of %s." % (name, ", ".join(allowed)))
    return v


def query_value(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_bool(name):
    if name not in request.args:
        return None
    v = request.args.get(name)
    low = v.lower() if isinstance(v, str) else v
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    bad("Query parameter %r must be a boolean." % name)


def required_query_enum(name, allowed):
    if name not in request.args:
        bad("Missing required query parameter %r." % name)
    v = request.args.get(name)
    if v not in allowed:
        bad("Query parameter %r must be one of %s." % (name, ", ".join(allowed)))
    return v

"""Low-level helpers: ids, timestamps, rounding, body extraction, pagination."""
import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import fail

_ALNUM = string.ascii_letters + string.digits


def new_uuid():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def wallclock_iso():
    return fmt_dt(datetime.now(timezone.utc))


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 string (Z or offset allowed) into an aware UTC datetime."""
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp string" % field)
    s = value.strip()
    candidate = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def rhu(dec):
    """Round half-up a Decimal to the nearest integer (cents)."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        fail("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    return body[name]


def as_str(value, name):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return value


def req_str(body, name):
    return as_str(req_field(body, name), name)


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return as_str(body[name], name)


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return value


def req_int(body, name):
    return as_int(req_field(body, name), name)


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return as_int(body[name], name)


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return body[name]


def req_dt(body, name):
    return parse_dt(req_field(body, name), name)


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    value = as_str(body[name], name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, sorted(allowed)))
    return value


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
    if offset < 0:
        offset = 0
    return limit, offset

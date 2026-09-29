"""Request-shape validation (PRD §2.8 step 3). Runs before any database read."""

import math
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        invalid("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


def _present(d, key):
    return key in d and d[key] is not None


def req_str(d, key):
    if not _present(d, key):
        invalid("Field '%s' is required." % key)
    v = d[key]
    if not isinstance(v, str) or v == "":
        invalid("Field '%s' must be a non-empty string." % key)
    return v


def opt_str(d, key, default=None):
    if not _present(d, key):
        return default
    return req_str(d, key)


def req_enum(d, key, allowed):
    v = req_str(d, key)
    if v not in allowed:
        invalid("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return v


def opt_enum(d, key, allowed, default=None):
    if not _present(d, key):
        return default
    return req_enum(d, key, allowed)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_number(d, key, min_value=None, exclusive_min=False, max_value=None):
    if not _present(d, key):
        invalid("Field '%s' is required." % key)
    v = d[key]
    if not _is_number(v):
        invalid("Field '%s' must be a number." % key)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        invalid("Field '%s' must be a finite number." % key)
    if min_value is not None:
        if exclusive_min and not v > min_value:
            invalid("Field '%s' must be greater than %s." % (key, min_value))
        if not exclusive_min and v < min_value:
            invalid("Field '%s' must be at least %s." % (key, min_value))
    if max_value is not None and v > max_value:
        invalid("Field '%s' must be at most %s." % (key, max_value))
    return v


def opt_number(d, key, default=None, min_value=None, exclusive_min=False, max_value=None):
    if not _present(d, key):
        return default
    return req_number(d, key, min_value, exclusive_min, max_value)


def req_int(d, key, min_value=None):
    if not _present(d, key):
        invalid("Field '%s' is required." % key)
    v = d[key]
    if not isinstance(v, int) or isinstance(v, bool):
        invalid("Field '%s' must be an integer." % key)
    if min_value is not None and v < min_value:
        invalid("Field '%s' must be at least %s." % (key, min_value))
    return v


def opt_bool(d, key, default=False):
    if not _present(d, key):
        return default
    v = d[key]
    if not isinstance(v, bool):
        invalid("Field '%s' must be a boolean." % key)
    return v


def req_date(d, key):
    v = req_str(d, key)
    if not DATE_RE.match(v):
        invalid("Field '%s' must be a YYYY-MM-DD date." % key)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        invalid("Field '%s' must be a valid calendar date." % key)
    return v


def parse_datetime(value, key):
    if not isinstance(value, str) or not value:
        invalid("Field '%s' must be an ISO 8601 datetime string." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        invalid("Field '%s' must be an ISO 8601 datetime string." % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(d, key):
    if not _present(d, key):
        invalid("Field '%s' is required." % key)
    raw = d[key]
    return raw, parse_datetime(raw, key)


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            invalid("Query parameter 'offset' must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        invalid("Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return v


def query_str(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total

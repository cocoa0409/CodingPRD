"""Request shape validation (PRD 2.9 step 3) and pagination (PRD 2.3)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ERR_INVALID_REQUEST, fail

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]00:?00)?$"
)


def body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, "request body is not valid JSON")
    if not isinstance(parsed, dict):
        fail(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return parsed


def _present(data, key):
    return key in data and data[key] is not None


def string(data, key, min_len=1, max_len=None, required=True, default=None):
    if not _present(data, key):
        if required:
            fail(ERR_INVALID_REQUEST, "%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "%s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        fail(ERR_INVALID_REQUEST, "%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail(ERR_INVALID_REQUEST, "%s must be at most %d characters" % (key, max_len))
    return value


def integer(data, key, minimum=None, maximum=None, required=True, default=None):
    if not _present(data, key):
        if required:
            fail(ERR_INVALID_REQUEST, "%s is required" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    if minimum is not None and value < minimum:
        fail(ERR_INVALID_REQUEST, "%s must be >= %d" % (key, minimum))
    if maximum is not None and value > maximum:
        fail(ERR_INVALID_REQUEST, "%s must be <= %d" % (key, maximum))
    return value


def boolean(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            fail(ERR_INVALID_REQUEST, "%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        fail(ERR_INVALID_REQUEST, "%s must be a boolean" % key)
    return value


def enum(data, key, allowed, required=True, default=None):
    if not _present(data, key):
        if required:
            fail(ERR_INVALID_REQUEST, "%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        fail(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def one_of_int(data, key, allowed, required=True, default=None):
    value = integer(data, key, required=required, default=default)
    if value is None:
        return None
    if value not in allowed:
        fail(
            ERR_INVALID_REQUEST,
            "%s must be one of %s" % (key, ", ".join(str(a) for a in allowed)),
        )
    return value


def parse_iso(value, key="datetime"):
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "%s must be an ISO 8601 UTC string" % key)
    match = _DT_RE.match(value.strip())
    if not match:
        fail(ERR_INVALID_REQUEST, "%s must be an ISO 8601 UTC instant" % key)
    year, month, day, hour, minute, second, frac = match.groups()[:7]
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        fail(ERR_INVALID_REQUEST, "%s is not a valid instant" % key)


def datetime_field(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            fail(ERR_INVALID_REQUEST, "%s is required" % key)
        return default
    return parse_iso(data[key], key)


def identifier(data, key, required=True, default=None):
    return string(data, key, min_len=1, max_len=200, required=required, default=default)


# -- query parameters ------------------------------------------------------
_INT_RE = re.compile(r"^-?\d+$")


def pagination():
    limit = 10
    offset = 0
    args = request.args
    if "limit" in args:
        raw = (args.get("limit") or "").strip()
        if not _INT_RE.match(raw):
            fail(ERR_INVALID_REQUEST, "limit must be an integer")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args:
        raw = (args.get("offset") or "").strip()
        if not _INT_RE.match(raw):
            fail(ERR_INVALID_REQUEST, "offset must be an integer")
        offset = int(raw)
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def query_enum(key, allowed):
    if key not in request.args:
        return None
    value = request.args.get(key)
    if value not in allowed:
        fail(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def query_value(key):
    if key not in request.args:
        return None
    return request.args.get(key)

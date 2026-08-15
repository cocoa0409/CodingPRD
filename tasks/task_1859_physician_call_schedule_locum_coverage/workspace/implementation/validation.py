"""Request shape validation helpers — priority 4, ERR_INVALID_REQUEST (PRD §2.11)."""
import re
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        _bad("%s is required and must be a string" % name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], str):
        _bad("%s must be a string" % name)
    return body[name]


def req_int(body, name):
    v = body.get(name)
    if not is_int(v):
        _bad("%s is required and must be an integer" % name)
    return v


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not is_int(body[name]):
        _bad("%s must be an integer" % name)
    return body[name]


def opt_num(body, name, default=None):
    """Numeric field stored as Decimal (exact, no float arithmetic)."""
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("%s must be a number" % name)
    return Decimal(str(v))


def parse_date_str(v, name):
    if not isinstance(v, str) or not DATE_RE.match(v):
        _bad("%s must be an ISO YYYY-MM-DD date string" % name)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        _bad("%s must be an ISO YYYY-MM-DD date string" % name)
    return v


def req_date(body, name):
    return parse_date_str(body.get(name), name)


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        _bad("%s is required and must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, allowed)


def parse_iso8601(v, name):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(v, str):
        _bad("%s must be an ISO 8601 datetime string" % name)
    text = v.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        _bad("%s must be an ISO 8601 datetime string" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

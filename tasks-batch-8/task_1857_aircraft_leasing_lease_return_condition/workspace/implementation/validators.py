"""Request-body and parameter validation helpers (pipeline step 4)."""
import re
from datetime import datetime

from flask import request

from errors import bad_request

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise bad_request("Request body must be a JSON object")
    return b


def _is_int(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float) and v.is_integer():
        return True
    return False


def req_str(b, name):
    v = b.get(name)
    if v is None:
        raise bad_request("Missing required field: %s" % name)
    if not isinstance(v, str) or v == "":
        raise bad_request("Field %s must be a non-empty string" % name)
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str):
        raise bad_request("Field %s must be a string" % name)
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if v is None:
        raise bad_request("Missing required field: %s" % name)
    if v not in allowed:
        raise bad_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def req_int(b, name, min_v=None):
    v = b.get(name)
    if v is None:
        raise bad_request("Missing required field: %s" % name)
    if not _is_int(v):
        raise bad_request("Field %s must be an integer" % name)
    v = int(v)
    if min_v is not None and v < min_v:
        raise bad_request("Field %s must be >= %s" % (name, min_v))
    return v


def opt_int(b, name, min_v=None, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not _is_int(v):
        raise bad_request("Field %s must be an integer" % name)
    v = int(v)
    if min_v is not None and v < min_v:
        raise bad_request("Field %s must be >= %s" % (name, min_v))
    return v


def req_number(b, name, min_v=None):
    v = b.get(name)
    if v is None:
        raise bad_request("Missing required field: %s" % name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request("Field %s must be a number" % name)
    if min_v is not None and v < min_v:
        raise bad_request("Field %s must be >= %s" % (name, min_v))
    return v


def opt_number(b, name, min_v=None, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request("Field %s must be a number" % name)
    if min_v is not None and v < min_v:
        raise bad_request("Field %s must be >= %s" % (name, min_v))
    return v


def req_date(b, name):
    v = req_str(b, name)
    if not DATE_RE.match(v):
        raise bad_request("Field %s must be an ISO date (YYYY-MM-DD)" % name)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise bad_request("Field %s must be a valid calendar date" % name)
    return v


def req_month(b, name):
    v = req_str(b, name)
    if not MONTH_RE.match(v):
        raise bad_request("Field %s must be a month (YYYY-MM)" % name)
    m = int(v[5:7])
    if m < 1 or m > 12:
        raise bad_request("Field %s must be a valid month (YYYY-MM)" % name)
    return v


def month_param(name):
    raw = request.args.get(name)
    if raw is None:
        raise bad_request("Missing required query parameter: %s" % name)
    if not MONTH_RE.match(raw):
        raise bad_request("Query parameter %s must be a month (YYYY-MM)" % name)
    m = int(raw[5:7])
    if m < 1 or m > 12:
        raise bad_request("Query parameter %s must be a valid month (YYYY-MM)" % name)
    return raw

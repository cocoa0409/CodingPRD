"""Request parsing and field-validation helpers (priority-10 style checks)."""
from datetime import date

from flask import request

from db import parse_iso_dt
from errors import bad_request


def body():
    j = request.get_json(silent=True)
    if isinstance(j, dict):
        return j
    return {}


def present(j, name):
    return name in j and j[name] is not None


def require_str(j, name):
    if not present(j, name) or not isinstance(j[name], str) or j[name] == "":
        raise bad_request("Missing or invalid required field: %s" % name)
    return j[name]


def optional_str(j, name):
    if not present(j, name):
        return None
    if not isinstance(j[name], str):
        raise bad_request("Invalid field: %s" % name)
    return j[name]


def require_bool(j, name):
    if not present(j, name) or not isinstance(j[name], bool):
        raise bad_request("Missing or invalid required field: %s" % name)
    return j[name]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_int(j, name, lo=None, hi=None):
    if not present(j, name) or not _is_int(j[name]):
        raise bad_request("Missing or invalid required field: %s" % name)
    v = j[name]
    if lo is not None and v < lo:
        raise bad_request("Field %s below minimum %s" % (name, lo))
    if hi is not None and v > hi:
        raise bad_request("Field %s above maximum %s" % (name, hi))
    return v


def optional_enum(j, name, allowed, default=None):
    if not present(j, name):
        return default
    if not isinstance(j[name], str) or j[name] not in allowed:
        raise bad_request("Invalid value for %s" % name)
    return j[name]


def require_enum(j, name, allowed):
    if not present(j, name) or not isinstance(j[name], str) or j[name] not in allowed:
        raise bad_request("Missing or invalid value for %s" % name)
    return j[name]


def parse_date_value(v):
    """Accept YYYY-MM-DD or ISO datetime; return a date or None."""
    if not isinstance(v, str):
        return None
    txt = v.strip()
    if len(txt) == 10:
        try:
            return date.fromisoformat(txt)
        except ValueError:
            return None
    dt = parse_iso_dt(txt)
    if dt is None:
        return None
    return dt.date()


def require_date(j, name):
    """Returns (raw_string, parsed_date)."""
    if not present(j, name):
        raise bad_request("Missing required field: %s" % name)
    d = parse_date_value(j[name])
    if d is None:
        raise bad_request("Invalid date for field: %s" % name)
    return j[name], d

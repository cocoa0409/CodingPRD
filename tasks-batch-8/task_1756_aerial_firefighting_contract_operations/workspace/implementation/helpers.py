"""Parsing, shape validation, and entity serialization helpers."""
import re
from datetime import datetime, date, timezone

from errors import bad_request

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    from flask import request
    if not request.is_json:
        raise bad_request("request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise bad_request("request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None:
        raise bad_request(f"missing required field: {field}")
    if not isinstance(v, str):
        raise bad_request(f"field {field} must be a string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise bad_request(f"field {field} must be a string")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None:
        raise bad_request(f"missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"field {field} must be an integer")
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise bad_request(f"field {field} must be an integer")
    return v


def req_number(data, field):
    v = data.get(field)
    if v is None:
        raise bad_request(f"missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request(f"field {field} must be a number")
    return v


def req_enum(data, field, members):
    v = req_str(data, field)
    if v not in members:
        raise bad_request(f"field {field} must be one of {sorted(members)}")
    return v


def opt_enum(data, field, members, default=None):
    v = data.get(field, default)
    if v is not None:
        if not isinstance(v, str) or v not in members:
            raise bad_request(f"field {field} must be one of {sorted(members)}")
    return v


def req_date(data, field):
    v = req_str(data, field)
    return parse_date(v, field)


def parse_date(v, field="date"):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise bad_request(f"field {field} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise bad_request(f"field {field} must be a valid YYYY-MM-DD date")


def parse_datetime(v, field="datetime"):
    if not isinstance(v, str):
        raise bad_request(f"field {field} must be an ISO 8601 UTC datetime string")
    s = v
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise bad_request(f"field {field} must be an ISO 8601 UTC datetime")
    if dt.tzinfo is None:
        raise bad_request(f"field {field} must carry a UTC offset")
    return dt.astimezone(timezone.utc)


def req_datetime(data, field):
    return parse_datetime(req_str(data, field), field)


def opt_datetime(data, field, default=None):
    v = data.get(field, default)
    if v is None:
        return None
    return parse_datetime(v, field)


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def str_to_date(s):
    return date.fromisoformat(s)

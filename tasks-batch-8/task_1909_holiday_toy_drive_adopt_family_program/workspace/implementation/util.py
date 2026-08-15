"""Shared helpers: timestamps, request body validation, type coercion."""

import math
import re
from datetime import datetime, timezone, date

from flask import request

from errors import err_invalid_request

ISO_Z_RE = re.compile(r"Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE4_RE = re.compile(r"^\d{4}$")
AGENCY_CODE_RE = re.compile(r"^[A-Z0-9]{3,16}$")


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime into an aware UTC datetime. 400 on failure."""
    if not isinstance(value, str):
        raise err_invalid_request("%s must be an ISO 8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except (ValueError, TypeError):
        raise err_invalid_request("%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse a strict YYYY-MM-DD date. 400 on failure."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise err_invalid_request("%s must be a YYYY-MM-DD date" % field)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise err_invalid_request("%s is not a valid calendar date" % field)


def get_body(required=False):
    """Return the JSON request body as a dict. Empty body -> {} unless required."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise err_invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise err_invalid_request("Missing required field: %s" % name)
    return body[name]


def opt_field(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err_invalid_request("%s must be a non-empty string" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request("%s must be an integer" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err_invalid_request("%s must be a boolean" % field)
    return value


def as_str_list(value, field):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise err_invalid_request("%s must be a list of strings" % field)
    return list(value)


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise err_invalid_request("%s must be one of {%s}" % (field, ", ".join(allowed)))
    return value


def age_years_at(dob_date, distribution_dt):
    """Whole-year age floored from whole days / 365.25."""
    dob_dt = datetime(dob_date.year, dob_date.month, dob_date.day, tzinfo=timezone.utc)
    dist = distribution_dt
    if dist.tzinfo is None:
        dist = dist.replace(tzinfo=timezone.utc)
    delta_days = math.floor((dist - dob_dt).total_seconds() / 86400.0)
    return math.floor(delta_days / 365.25)


def age_band_for(years):
    if years < 1:
        return "INFANT"
    if years < 3:
        return "TODDLER"
    if years < 5:
        return "PRESCHOOL"
    if years < 10:
        return "SCHOOL_AGE"
    if years < 13:
        return "PRETEEN"
    return "TEEN"

"""Body / query validation helpers and identifier resolution.

The precedence order of PRD 2.6 is enforced by the *call order* inside each
route handler; these helpers only raise the error the rule names.
"""

import json
import re
from datetime import date, datetime, timedelta

from flask import request

from db import db
from errors import fail

MISSING = object()

SCHOOL_YEAR_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------- body ------
def get_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def raw_field(body, name):
    """Value as supplied, or MISSING when the key is absent."""
    if name in body:
        return body[name]
    return MISSING


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def need_string(body, name, min_len=1, max_len=None):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def opt_string(body, name, default=None, min_len=1, max_len=None,
               allow_null=True):
    value = raw_field(body, name)
    if value is MISSING:
        return default
    if value is None:
        if allow_null:
            return None
        _bad(name, "must not be null")
    return need_string(body, name, min_len, max_len)


def need_int(body, name, minimum=None, maximum=None):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        return default
    return need_int(body, name, minimum, maximum)


def need_number(body, name, minimum=None, maximum=None, exclusive_min=None):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if exclusive_min is not None and value <= exclusive_min:
        _bad(name, "must be greater than %s" % exclusive_min)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def opt_number(body, name, default=None, minimum=None, maximum=None,
               exclusive_min=None):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        return default
    return need_number(body, name, minimum, maximum, exclusive_min)


def need_bool(body, name):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(body, name, default=False):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        return default
    return need_bool(body, name)


def need_enum(body, name, allowed):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(body, name, allowed, default=None):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        return default
    return need_enum(body, name, allowed)


def need_school_year(body, name):
    value = need_string(body, name, 1, 20)
    if not SCHOOL_YEAR_RE.match(value):
        _bad(name, "must be written as YYYY-YY")
    return value


def parse_date_string(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def need_date(body, name):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    parsed = parse_date_string(value)
    if parsed is None:
        _bad(name, "must be a calendar date written as YYYY-MM-DD")
    return value, parsed


def need_string_array(body, name, allowed=None, min_items=1):
    value = raw_field(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if not isinstance(value, list):
        _bad(name, "must be an array")
    if len(value) < min_items:
        _bad(name, "must contain at least %d element(s)" % min_items)
    for element in value:
        if not isinstance(element, str):
            _bad(name, "must contain only strings")
        if allowed is not None and element not in allowed:
            _bad(name, "elements must be one of %s" % ", ".join(allowed))
    return value


# ---------------------------------------------------------- pagination -----
def pagination():
    """Rule 7: limit in 1..100, offset >= 0 (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except Exception:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer from 1 through 100.")
        if str(limit_raw).strip() != str(limit):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer from 1 through 100.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer from 1 through 100.")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except Exception:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
        if str(offset_raw).strip() != str(offset):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ------------------------------------------------- identifier resolution ---
_TABLES = {
    "school": ("schools", "ERR_SCHOOL_NOT_FOUND"),
    "policy": ("policies", "ERR_POLICY_NOT_FOUND"),
    "room": ("rooms", "ERR_ROOM_NOT_FOUND"),
    "set_aside": ("set_asides", "ERR_SET_ASIDE_NOT_FOUND"),
    "projection": ("projections", "ERR_PROJECTION_NOT_FOUND"),
    "budget": ("budgets", "ERR_BUDGET_NOT_FOUND"),
    "crew": ("crews", "ERR_CREW_NOT_FOUND"),
    "study": ("studies", "ERR_STUDY_NOT_FOUND"),
    "unit": ("units", "ERR_UNIT_NOT_FOUND"),
    "site": ("sites", "ERR_SITE_NOT_FOUND"),
    "request": ("requests", "ERR_REQUEST_NOT_FOUND"),
    "permit": ("permits", "ERR_PERMIT_NOT_FOUND"),
    "schedule": ("schedules", "ERR_SCHEDULE_NOT_FOUND"),
    "disposal": ("disposals", "ERR_DISPOSAL_NOT_FOUND"),
}


def lookup(kind, identifier):
    table_name, error_id = _TABLES[kind]
    table = getattr(db, table_name)
    if not isinstance(identifier, str) or identifier not in table:
        fail(error_id, "%s '%s' does not resolve." % (kind, identifier))
    return table[identifier]


def resolve_body_fk(kind, body, field, required=True):
    """Rule 5: resolve a body foreign key.

    A field that is absent or null is left for the rule-6 body-shape check so
    that the declared precedence order is preserved.
    """
    value = raw_field(body, field)
    if value is MISSING or value is None:
        return None
    if not isinstance(value, str):
        # A present-but-unusable identifier cannot resolve; rule 5 owns it.
        table_name, error_id = _TABLES[kind]
        fail(error_id, "%s '%s' does not resolve." % (kind, value))
    return lookup(kind, value)


def days_between(later, earlier):
    return (later - earlier).days


def add_days(day, count):
    return day + timedelta(days=count)


def as_date(value):
    if isinstance(value, date):
        return value
    return parse_date_string(value)

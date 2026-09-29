"""Shape validation, numeric and date helpers."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MISSING = object()


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


# ---------------------------------------------------------------- rounding
def rhu(value):
    """Round half up to a whole unit (cents) and return an int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(value):
    """Round half up to four decimal places, returning a Decimal."""
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ---------------------------------------------------------------- body access
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be valid JSON.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(data, key):
    return key in data and data[key] is not None


def get_str(data, key, required=True, allow_empty=False, default=None):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must be non-empty." % key)
    return value


def get_bool(data, key, required=True, default=None):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    bad("Field '%s' must be a boolean." % key)


def get_int(data, key, required=True, default=None, minimum=None, maximum=None):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % key)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if value != int(value):
            bad("Field '%s' must be an integer." % key)
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        try:
            candidate = Decimal(text)
        except (InvalidOperation, ValueError):
            bad("Field '%s' must be an integer." % key)
        if candidate != candidate.to_integral_value():
            bad("Field '%s' must be an integer." % key)
        parsed = int(candidate)
    else:
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and parsed < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and parsed > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return parsed


def get_dec(data, key, required=True, default=None, minimum=None, maximum=None):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % key)
    if isinstance(value, (int, float, str, Decimal)):
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            bad("Field '%s' must be a number." % key)
    else:
        bad("Field '%s' must be a number." % key)
    if not parsed.is_finite():
        bad("Field '%s' must be a finite number." % key)
    if minimum is not None and parsed < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and parsed > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s." % (key, maximum))
    return parsed


def get_enum(data, key, allowed, required=True, default=None):
    value = get_str(data, key, required=required, default=default)
    if value is None:
        return None
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def get_id(data, key, required=True, default=None):
    """A foreign key: must be a non-empty string when supplied."""
    return get_str(data, key, required=required, default=default)


def get_date(data, key, required=True, default=None):
    value = get_str(data, key, required=required, default=None)
    if value is None:
        return default
    return parse_date(value, key)


def parse_date(value, key="date"):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        bad("Field '%s' must be an ISO-8601 calendar date (YYYY-MM-DD)." % key)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        bad("Field '%s' must be an ISO-8601 calendar date (YYYY-MM-DD)." % key)


def parse_datetime(value, key="current_utc"):
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an ISO-8601 UTC timestamp." % key)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    bad("Field '%s' must be an ISO-8601 UTC timestamp." % key)


def get_str_list(data, key, required=True, default=None, min_len=None):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            bad("Field '%s' must be an array of identifiers." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must hold at least %d element(s)." % (key, min_len))
    return value


# ---------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        limit = _query_int("limit", args.get("limit"))
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        offset = _query_int("offset", args.get("offset"))
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def _query_int(name, value):
    try:
        candidate = Decimal(value.strip())
    except (InvalidOperation, AttributeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
    if candidate != candidate.to_integral_value():
        bad("Query parameter '%s' must be an integer." % name)
    return int(candidate)


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)


def bool_filter(name):
    """Read an optional boolean query filter; an unrecognised value matches nothing."""
    raw_value = request.args.get(name)
    if raw_value is None or raw_value == "":
        return None
    lowered = raw_value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return "__no_match__"


def date_filter(name):
    raw_value = request.args.get(name)
    if raw_value is None or raw_value == "":
        return None
    return parse_date(raw_value, name)


# ---------------------------------------------------------------- date math
def elapsed_months(start, end):
    """PRD 3.3 elapsed month count between two dates."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def day_gap(left, right):
    return abs((left - right).days)


def as_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return parse_date(value)

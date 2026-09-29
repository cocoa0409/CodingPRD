"""Request schema validation (PRD 2.9 band 3) and query-parameter parsing."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON body; a missing or non-object body reads as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("The request body must be a JSON object.")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None, required=True, non_blank=True):
    if not _present(data, name):
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if non_blank and not value.strip():
        raise bad("Field '%s' may not be blank." % name)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' is longer than %d characters." % (name, max_len))
    return value


def req_int(data, name, min_v=None, max_v=None, required=True, allowed=None):
    if not _present(data, name):
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    if min_v is not None and value < min_v:
        raise bad("Field '%s' must be >= %d." % (name, min_v))
    if max_v is not None and value > max_v:
        raise bad("Field '%s' must be <= %d." % (name, max_v))
    if allowed is not None and value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def req_enum(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            raise bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def req_date(data, name, required=True):
    """ISO 8601 calendar date, YYYY-MM-DD (PRD 2.11)."""
    if not _present(data, name):
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise bad("Field '%s' is not a valid calendar date." % name)


def req_pct(data, name, required=True):
    """A number strictly greater than 0, at most 100, at most 2 decimal places."""
    if not _present(data, name):
        if required:
            raise bad("Field '%s' is required." % name)
        return None
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise bad("Field '%s' must be a number." % name)
    if dec <= 0 or dec > Decimal("100"):
        raise bad("Field '%s' must be greater than 0 and at most 100." % name)
    if -dec.as_tuple().exponent > 2:
        raise bad("Field '%s' carries at most two decimal places." % name)
    return dec


def req_id_list(data, name):
    """Optional list of id strings."""
    if not _present(data, name):
        return []
    value = data[name]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array of ids." % name)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise bad("Field '%s' must contain non-empty id strings." % name)
    return value


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_v = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit_v < PAGINATION_MIN_LIMIT or limit_v > PAGINATION_MAX_LIMIT:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if offset is None or offset == "":
        offset_v = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset_v < 0:
            raise bad("Query parameter 'offset' must be >= 0.")
    return limit_v, offset_v


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)


def parse_date_value(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def as_date(value):
    """Stored YYYY-MM-DD string -> date."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def paginate(rows, limit, offset):
    return rows[offset: offset + limit], len(rows)

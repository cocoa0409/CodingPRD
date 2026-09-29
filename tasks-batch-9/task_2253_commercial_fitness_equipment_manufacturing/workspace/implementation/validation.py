"""Schema validation helpers (validation ladder rung 7, ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_iso

_MISSING = object()


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """Parsed JSON object body; an absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        invalid("Request body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        invalid("Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# scalar field helpers
# ---------------------------------------------------------------------------
def _present(body, key, required):
    if key not in body or body[key] is None:
        if required:
            invalid("Field '%s' is required." % key)
        return False
    return True


def field_str(body, key, required=True, min_len=1, max_len=None, default=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        invalid("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def field_int(body, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        invalid("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("Field '%s' must be <= %s." % (key, maximum))
    return value


def field_decimal(
    body, key, required=True, minimum=None, maximum=None, exclusive_min=None, default=None
):
    if not _present(body, key, required):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        invalid("Field '%s' must be a number." % key)
    if not dec.is_finite():
        invalid("Field '%s' must be a finite number." % key)
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        invalid("Field '%s' must be > %s." % (key, exclusive_min))
    if minimum is not None and dec < Decimal(str(minimum)):
        invalid("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        invalid("Field '%s' must be <= %s." % (key, maximum))
    return dec


def field_bool(body, key, required=True, default=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % key)
    return value


def field_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def field_enum_array(
    body, key, allowed, required=True, non_empty=True, default=None
):
    if not _present(body, key, required):
        return list(default) if default is not None else default
    value = body[key]
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % key)
    if non_empty and not value:
        invalid("Field '%s' must not be empty." % key)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("Field '%s' members must be one of %s." % (key, ", ".join(allowed)))
        if item in seen:
            invalid("Field '%s' must not contain duplicates." % key)
        seen.add(item)
    return list(value)


def field_datetime(body, key, required=True, default=None):
    """Returns (raw_string, datetime). Client strings are echoed verbatim."""
    if not _present(body, key, required):
        return (default, None)
    value = body[key]
    if not isinstance(value, str):
        invalid("Field '%s' must be an ISO-8601 timestamp string." % key)
    parsed = parse_iso(value)
    if parsed is None:
        invalid("Field '%s' must be a valid ISO-8601 timestamp." % key)
    return (value, parsed)


def field_id(body, key, required=True, default=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, str) or not value:
        invalid("Field '%s' must be a non-empty string identifier." % key)
    return value


# ---------------------------------------------------------------------------
# query helpers
# ---------------------------------------------------------------------------
def paging():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer.")
        if str(raw).strip() != str(limit):
            invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer.")
        if str(raw).strip() != str(offset):
            invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            invalid("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_enum(key, allowed):
    if key not in request.args:
        return None
    value = request.args.get(key)
    if value not in allowed:
        invalid("Query parameter '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def query_str(key):
    if key not in request.args:
        return None
    return request.args.get(key)


def paginate(rows, limit, offset, sort_key=None):
    if sort_key is None:
        sort_key = lambda row: (row["created_at"], row["id"])
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total

"""Request-shape validation (precedence priority 4) and pagination (priority 5)."""

from decimal import Decimal

from flask import request

from errors import ApiError, bad_request
from store import parse_instant

_MISSING = object()


def json_body(required=True):
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            raise bad_request("A JSON request body is required.")
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if body is None:
        if required:
            raise bad_request("A JSON request body is required.")
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object.")
    return body


def _present(body, key):
    return key in body and body[key] is not None


def field_string(body, key, min_len=1, max_len=None, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % key)
    if not value.strip():
        raise bad_request("Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def field_integer(body, key, minimum=None, maximum=None, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be at most %s." % (key, maximum))
    return value


def field_number(body, key, minimum=None, maximum=None, required=True, default=_MISSING,
                 exclusive_min=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % key)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise bad_request("Field '%s' must be a finite number." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be at least %s." % (key, minimum))
    if exclusive_min is not None and not value > exclusive_min:
        raise bad_request("Field '%s' must be greater than %s." % (key, exclusive_min))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be at most %s." % (key, maximum))
    return value


def field_boolean(body, key, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return value


def field_enum(body, key, allowed, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def field_enum_array(body, key, allowed, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, list) or not value:
        raise bad_request("Field '%s' must be a non-empty array." % key)
    seen = set()
    for member in value:
        if not isinstance(member, str) or member not in allowed:
            raise bad_request(
                "Field '%s' members must be one of %s." % (key, ", ".join(sorted(allowed)))
            )
        if member in seen:
            raise bad_request("Field '%s' must not contain duplicates." % key)
        seen.add(member)
    return list(value)


def field_instant(body, key, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 datetime string." % key)
    parsed = parse_instant(value)
    if parsed is None:
        raise bad_request("Field '%s' is not a valid ISO 8601 datetime." % key)
    return parsed


def field_identifier(body, key, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Field '%s' must be a non-empty string identifier." % key)
    return value


def field_date(body, key, required=True, default=_MISSING):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required." % key)
        return None if default is _MISSING else default
    value = body[key]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a YYYY-MM-DD string." % key)
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise bad_request("Field '%s' must be a YYYY-MM-DD date." % key)
    parsed = parse_instant(text + "T00:00:00Z")
    if parsed is None:
        raise bad_request("Field '%s' must be a valid YYYY-MM-DD date." % key)
    return text


def require_interval(start, end, start_key, end_key):
    if start is None or end is None:
        return
    if not end > start:
        raise bad_request("Field '%s' must be strictly later than '%s'." % (end_key, start_key))


def decimal_of(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _as_int(raw)
        if limit is None or limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        offset = _as_int(raw)
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
    return limit, offset


def _as_int(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        return None
    return int(text)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total

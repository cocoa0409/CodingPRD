"""Request-shape validation helpers.

Everything raised from this module is ERR_INVALID_REQUEST (PRD Section 2.8
rung 3) except where explicitly noted by the caller.
"""

import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError, bad_request
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MISSING = object()


def json_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object.")
    return body


def _present(body, key):
    return key in body and body[key] is not None


def require_present(body, key):
    if not _present(body, key):
        raise bad_request("Field '%s' is required and must not be null." % key)


def get_string(body, key, required=True, default=None, allow_empty=False):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise bad_request("Field '%s' must be a non-empty string." % key)
    return value


def get_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return value


def get_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        elif isinstance(value, str):
            try:
                value = int(value.strip())
            except (ValueError, AttributeError):
                raise bad_request("Field '%s' must be an integer." % key)
        else:
            raise bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be greater than or equal to %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be less than or equal to %s." % (key, maximum))
    return value


def _to_decimal(key, value):
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be a decimal number." % key)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            raise bad_request("Field '%s' must be a decimal number." % key)
        try:
            return Decimal(text)
        except InvalidOperation:
            raise bad_request("Field '%s' must be a decimal number." % key)
    raise bad_request("Field '%s' must be a decimal number." % key)


def get_money(body, key, required=True, default=None, allow_zero=True):
    """Monetary amounts: non-negative, at most 2 decimal places (PRD 2.3)."""
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = _to_decimal(key, body[key])
    if not value.is_finite():
        raise bad_request("Field '%s' must be a finite decimal number." % key)
    if value < 0:
        raise bad_request("Field '%s' must not be negative." % key)
    if not allow_zero and value == 0:
        raise bad_request("Field '%s' must be strictly positive." % key)
    if -value.as_tuple().exponent > 2:
        raise bad_request("Field '%s' must carry at most two decimal places." % key)
    return value.quantize(Decimal("0.01"))


def get_share_pct(body, key, required=True, default=None):
    """Share percentages: decimals in [0.0000, 1.0000] carried to 4 places."""
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = _to_decimal(key, body[key])
    if not value.is_finite() or value < 0 or value > 1:
        raise bad_request("Field '%s' must lie between 0.0000 and 1.0000 inclusive." % key)
    return value.quantize(Decimal("0.0001"))


def get_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "Field '%s' must be one of: %s." % (key, ", ".join(sorted(allowed)))
        )
    return value


def get_date(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise bad_request("Field '%s' must be an ISO-8601 date (YYYY-MM-DD)." % key)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise bad_request("Field '%s' must be a valid calendar date." % key)


def get_time_of_day(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise bad_request("Field '%s' must be a UTC time of day (HH:MM)." % key)
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def parse_instant(key, value):
    if not isinstance(value, str) or value.strip() == "":
        raise bad_request("Field '%s' must be an ISO-8601 UTC instant." % key)
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise bad_request("Field '%s' must be an ISO-8601 UTC instant." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=parsed.microsecond)


def get_instant(body, key, required=True, default=None):
    """Returns (datetime, raw_string). Instants compare at whole-second
    resolution (PRD Section 3.9)."""
    if not _present(body, key):
        if required:
            raise bad_request("Field '%s' is required and must not be null." % key)
        return default, None
    raw = body[key]
    parsed = parse_instant(key, raw).replace(microsecond=0)
    return parsed, raw


def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise bad_request(
                "Query parameter 'limit' must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
            )
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be greater than or equal to 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad_request(
            "Query parameter '%s' must be one of: %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def query_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad_request("Query parameter '%s' must be a boolean." % name)

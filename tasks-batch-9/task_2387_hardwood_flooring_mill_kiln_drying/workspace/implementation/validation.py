"""Schema screening (PRD section 2.7 step 3) and pagination parsing."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError, invalid

MISSING = object()

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def body_json():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise invalid("Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object.")
    return data


def _present(body, name):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return None, False
    return value, True


def req_str(body, name, allow_blank=False):
    value, present = _present(body, name)
    if not present:
        raise invalid("%s is required." % name)
    if not isinstance(value, str):
        raise invalid("%s must be a string." % name)
    if not allow_blank and value.strip() == "":
        raise invalid("%s must not be blank." % name)
    return value


def opt_str(body, name, allow_blank=False):
    value, present = _present(body, name)
    if not present:
        return None
    if not isinstance(value, str):
        raise invalid("%s must be a string." % name)
    if not allow_blank and value.strip() == "":
        raise invalid("%s must not be blank." % name)
    return value


def req_int(body, name, min_value=0):
    value, present = _present(body, name)
    if not present:
        raise invalid("%s is required." % name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("%s must be an integer." % name)
    if min_value is not None and value < min_value:
        raise invalid("%s must be at least %s." % (name, min_value))
    return value


def req_decimal(body, name, min_value=0):
    value, present = _present(body, name)
    if not present:
        raise invalid("%s is required." % name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("%s must be a number." % name)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise invalid("%s must be a number." % name)
    if not parsed.is_finite():
        raise invalid("%s must be a finite number." % name)
    if min_value is not None and parsed < Decimal(str(min_value)):
        raise invalid("%s must be at least %s." % (name, min_value))
    return parsed


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        raise invalid("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed):
    value = opt_str(body, name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def parse_datetime(raw, name):
    if not isinstance(raw, str):
        raise invalid("%s must be an ISO 8601 datetime string." % name)
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("%s must be an ISO 8601 datetime string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(body, name):
    value, present = _present(body, name)
    if not present:
        raise invalid("%s is required." % name)
    return parse_datetime(value, name)


def req_date(body, name):
    value, present = _present(body, name)
    if not present:
        raise invalid("%s is required." % name)
    if not isinstance(value, str):
        raise invalid("%s must be an ISO 8601 date string." % name)
    text = value.strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        raise invalid("%s must be an ISO 8601 date string." % name)


def req_ref(body, name):
    """A required reference to another resource id."""
    return req_str(body, name)


def opt_ref(body, name):
    return opt_str(body, name)


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise invalid("limit must be between 1 and 100.")

    if raw_offset is None or raw_offset == "":
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer.")
        if offset < 0:
            raise invalid("offset must be at least 0.")

    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise invalid("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


__all__ = [
    "ApiError",
    "body_json",
    "opt_enum",
    "opt_ref",
    "opt_str",
    "pagination",
    "parse_datetime",
    "query_enum",
    "query_str",
    "req_date",
    "req_datetime",
    "req_decimal",
    "req_enum",
    "req_int",
    "req_ref",
    "req_str",
]

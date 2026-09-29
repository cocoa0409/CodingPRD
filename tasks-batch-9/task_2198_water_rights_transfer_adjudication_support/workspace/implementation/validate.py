"""Priority 6 body / query well-formedness helpers (ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import response
from errors import ApiError

_MISSING = object()


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body(required=True):
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            return {}
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


def field(body, name, default=_MISSING):
    if name in body and body[name] is not None:
        return body[name]
    if default is _MISSING:
        return None
    return default


def has(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None):
    value = body.get(name)
    if value is None:
        invalid("Field '%s' is required." % name)
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    if len(value.strip()) < max(min_len, 1) and min_len >= 1:
        invalid("Field '%s' must be a non-blank string." % name)
    if min_len is not None and len(value) < min_len:
        invalid("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' exceeds %d characters." % (name, max_len))
    return value


def opt_str(body, name, min_len=1, max_len=None):
    if not has(body, name):
        return None
    return req_str(body, name, min_len=min_len, max_len=max_len)


def req_enum(body, name, allowed):
    value = body.get(name)
    if value is None:
        invalid("Field '%s' is required." % name)
    if not isinstance(value, str) or value not in allowed:
        invalid(
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def opt_enum(body, name, allowed):
    if not has(body, name):
        return None
    return req_enum(body, name, allowed)


def _to_decimal(name, value):
    if isinstance(value, bool):
        invalid("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            invalid("Field '%s' must be a number." % name)
        try:
            return Decimal(text)
        except InvalidOperation:
            invalid("Field '%s' must be a number." % name)
    invalid("Field '%s' must be a number." % name)


def req_decimal(body, name, gt=None, gte=None, lte=None):
    if not has(body, name):
        invalid("Field '%s' is required." % name)
    value = _to_decimal(name, body[name])
    if not value.is_finite():
        invalid("Field '%s' must be a finite number." % name)
    if gt is not None and not value > Decimal(str(gt)):
        invalid("Field '%s' must be greater than %s." % (name, gt))
    if gte is not None and value < Decimal(str(gte)):
        invalid("Field '%s' must be greater than or equal to %s." % (name, gte))
    if lte is not None and value > Decimal(str(lte)):
        invalid("Field '%s' must be less than or equal to %s." % (name, lte))
    return value


def opt_decimal(body, name, gt=None, gte=None, lte=None, default=None):
    if not has(body, name):
        return default
    return req_decimal(body, name, gt=gt, gte=gte, lte=lte)


def req_int(body, name, minimum=None, maximum=None):
    if not has(body, name):
        invalid("Field '%s' is required." % name)
    value = body[name]
    if isinstance(value, bool):
        invalid("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and float(value).is_integer():
        parsed = int(value)
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        parsed = int(value.strip())
    else:
        invalid("Field '%s' must be an integer." % name)
    if minimum is not None and parsed < minimum:
        invalid("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and parsed > maximum:
        invalid("Field '%s' must be at most %d." % (name, maximum))
    return parsed


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not has(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name, default=None):
    if not has(body, name):
        if default is None:
            invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def req_date(body, name):
    raw = req_str(body, name)
    parsed = clock.parse_date(raw)
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 date." % name)
    return raw, parsed


def opt_date(body, name):
    if not has(body, name):
        return None, None
    return req_date(body, name)


def req_instant(body, name):
    raw = req_str(body, name)
    parsed = clock.parse_iso(raw)
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return raw, parsed


# ---------------------------------------------------------------------------
# Query string helpers
# ---------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = response.PAGINATION_DEFAULT_LIMIT
    offset = response.PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not str(raw).strip().lstrip("-").isdigit():
            invalid("Query parameter 'limit' must be an integer.")
        limit = int(str(raw).strip())
        if limit < response.PAGINATION_MIN_LIMIT or limit > response.PAGINATION_MAX_LIMIT:
            invalid(
                "Query parameter 'limit' must be between %d and %d."
                % (response.PAGINATION_MIN_LIMIT, response.PAGINATION_MAX_LIMIT)
            )
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not str(raw).strip().lstrip("-").isdigit():
            invalid("Query parameter 'offset' must be an integer.")
        offset = int(str(raw).strip())
        if offset < 0:
            invalid("Query parameter 'offset' must be non-negative.")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        invalid(
            "Query parameter '%s' must be one of %s."
            % (name, ", ".join(sorted(allowed)))
        )
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if not str(raw).strip().lstrip("-").isdigit():
        invalid("Query parameter '%s' must be an integer." % name)
    return int(str(raw).strip())

"""Shape validation helpers (PRD section 2.6 tier 3 -> ERR_VALIDATION)."""

from decimal import Decimal

import store
from errors import ApiError


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def body():
    from flask import request
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(payload, name):
    return name in payload and payload[name] is not None


def require(payload, *names):
    for name in names:
        if not present(payload, name):
            bad("Field '%s' is required and must not be null." % name)


def as_str(payload, name, required=True, min_len=None, max_len=None,
           non_blank=True, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if non_blank and not value.strip():
        bad("Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def as_enum(payload, name, allowed, required=True, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def as_int(payload, name, required=True, minimum=None, maximum=None, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %d." % (name, maximum))
    return value


def as_decimal(payload, name, required=True, minimum=None, maximum=None,
               exclusive_min=None, places=2, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        bad("Field '%s' must be a number." % name)
    try:
        parsed = store.dec(value)
    except ApiError:
        bad("Field '%s' must be a number." % name)
    if parsed != parsed or parsed.is_infinite():
        bad("Field '%s' must be a finite number." % name)
    if minimum is not None and parsed < store.dec(minimum):
        bad("Field '%s' must be >= %s." % (name, minimum))
    if exclusive_min is not None and parsed <= store.dec(exclusive_min):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    if maximum is not None and parsed > store.dec(maximum):
        bad("Field '%s' must be <= %s." % (name, maximum))
    return store.rhu(parsed, places)


def as_bool(payload, name, required=False, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def as_id(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def as_date(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    parsed = store.parse_date(payload[name])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    return parsed


def as_datetime(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    parsed = store.parse_dt(payload[name])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


def as_str_list(payload, name, allowed=None, required=True, non_empty=True,
                default=None):
    if not present(payload, name):
        if required:
            bad("Field '%s' is required and must not be null." % name)
        return default
    value = payload[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("Field '%s' must contain non-empty strings." % name)
        if allowed is not None and item not in allowed:
            bad("Field '%s' must be a subset of %s." % (name, sorted(allowed)))
    if non_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % name)
    return value


LANG_RE = "abcdefghijklmnopqrstuvwxyz"


def language_code(payload, name, required=True, default=None):
    value = as_str(payload, name, required=required, default=default)
    if value is None:
        return None
    if len(value) != 2 or any(ch not in LANG_RE for ch in value):
        bad("Field '%s' must be a lowercase ISO 639-1 two-letter code." % name)
    return value


def country_code(payload, name, required=True, default=None):
    value = as_str(payload, name, required=required, default=default)
    if value is None:
        return None
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad("Field '%s' must be an uppercase ISO 3166-1 alpha-2 code." % name)
    return value


def upper_code(payload, name, min_len, max_len, required=True, default=None):
    value = as_str(payload, name, required=required, min_len=min_len,
                   max_len=max_len, default=default)
    if value is None:
        return None
    if value != value.upper():
        bad("Field '%s' must be uppercase." % name)
    return value


def a_number(payload, name):
    if not present(payload, name):
        return None
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if len(value) != 10 or value[0] != "A" or not value[1:].isdigit():
        bad("Field '%s' must match ^A[0-9]{9}$." % name)
    return value

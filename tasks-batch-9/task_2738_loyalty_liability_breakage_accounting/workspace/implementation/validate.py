"""Request-shape validation (ladder rung 5 — ERR_INVALID_REQUEST, HTTP 400)."""
from flask import request

from errors import ApiError
from util import parse_iso

MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def json_body():
    """Parse the JSON body. An absent/empty body is an empty object."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise bad("Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise bad("Request body must be a JSON object.")
    return body


def _raw(body, key):
    if key not in body:
        return MISSING
    return body[key]


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def field_int(body, key, required=True, default=None, minimum=None, maximum=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return default
    if not _is_int(value):
        raise bad("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("%s is below its minimum." % key)
    if maximum is not None and value > maximum:
        raise bad("%s is above its maximum." % key)
    return value


def field_string(body, key, required=True, default=None, max_length=None,
                 allow_empty=False):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return default
    if not isinstance(value, str):
        raise bad("%s must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise bad("%s must not be empty." % key)
    if max_length is not None and len(value) > max_length:
        raise bad("%s exceeds its maximum length." % key)
    return value


_UPPERCASE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def field_code(body, key, length, required=True, default=None):
    """A fixed-length uppercase alphabetic code (currency, US state)."""
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return default
    if not isinstance(value, str):
        raise bad("%s must be a string." % key)
    if len(value) != length or any(ch not in _UPPERCASE for ch in value):
        raise bad("%s must be exactly %d uppercase letters." % (key, length))
    return value


def field_bool(body, key, required=True, default=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return default
    if not isinstance(value, bool):
        raise bad("%s must be a boolean." % key)
    return value


def field_enum(body, key, allowed, required=True, default=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def field_datetime(body, key, required=True, default=None):
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return default
    if not isinstance(value, str):
        raise bad("%s must be an ISO-8601 timestamp string." % key)
    parsed = parse_iso(value)
    if parsed is None:
        raise bad("%s must be an ISO-8601 timestamp string." % key)
    return parsed


def field_ref(body, key, required=True):
    """A foreign-key string. Existence is resolved later (rung 7)."""
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return None
    if not isinstance(value, str) or value.strip() == "":
        raise bad("%s must be a non-empty string." % key)
    return value


TIERS = ("BASE", "SILVER", "GOLD", "PLATINUM")


def field_tier_multiplier(body, key, required=True, default=None):
    """Tier multiplier object.

    Shape and value-range violations are rung-5 ERR_INVALID_REQUEST; a key set
    that is not exactly the four tiers is rung-28 ERR_TIER_MULTIPLIER_KEYS_INVALID
    and is therefore checked by the caller after every other rung-5 field.
    """
    value = _raw(body, key)
    if value is MISSING or value is None:
        if required:
            raise bad("%s is required." % key)
        return default
    if not isinstance(value, dict):
        raise bad("%s must be an object keyed by tier." % key)
    for tier_key, tier_value in value.items():
        if not isinstance(tier_key, str):
            raise bad("%s keys must be strings." % key)
        if not _is_int(tier_value):
            raise bad("%s values must be integers." % key)
        if tier_value < 10000 or tier_value > 50000:
            raise bad("%s values must be between 10000 and 50000." % key)
    return value


def tier_keys_valid(mapping):
    return set(mapping.keys()) == set(TIERS)


def reject_unless(condition, message):
    if not condition:
        raise bad(message)

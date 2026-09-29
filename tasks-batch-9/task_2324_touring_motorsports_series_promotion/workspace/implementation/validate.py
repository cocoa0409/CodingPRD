"""Payload validation (ladder step 3, ERR_INVALID_REQUEST / 422)."""
import json
from datetime import date, datetime, timezone

from flask import request

from errors import fail

_MISSING = object()


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def parse_datetime(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if "T" not in text and "t" not in text:
        return None
    normalized = text
    if normalized.endswith("Z") or normalized.endswith("z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _absent(payload, key):
    return key not in payload or payload[key] is None


def field_string(payload, key, required=True, default=None):
    if _absent(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % key)
    if value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty" % key)
    return value


def field_int(payload, key, required=True, default=None, minimum=None):
    if _absent(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s" % (key, minimum))
    return value


def field_number(payload, key, required=True, default=None, minimum=None, maximum=None):
    if _absent(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s" % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must not exceed %s" % (key, maximum))
    return value


def field_bool(payload, key, required=False, default=False):
    if _absent(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % key)
    return value


def field_enum(payload, key, allowed, required=True, default=None):
    if _absent(payload, key):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def field_datetime(payload, key, required=True):
    """Returns (raw_string, aware datetime) — raw is echoed back verbatim."""
    if key not in payload or payload[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return None, None
    value = payload[key]
    parsed = parse_datetime(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime" % key)
    return value, parsed


def field_date(payload, key, required=True):
    if key not in payload or payload[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return None, None
    value = payload[key]
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 date (YYYY-MM-DD)" % key)
    return value, parsed


def field_id(payload, key, required=True):
    """A foreign key: string when present, may be explicitly null when optional."""
    if key not in payload or payload[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % key)
        return None
    value = payload[key]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a string identifier" % key)
    return value


def supplied(payload, key):
    return key in payload

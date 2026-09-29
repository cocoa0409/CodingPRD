"""Structural request-shape validation (PRD 2.11 stage 1).

These checks consult no stored data, which is why they outrank even
authentication in the global precedence ladder.
"""
import re

from flask import request

from db import parse_date, parse_dt
from errors import ApiError

CODE_RE = re.compile(r"^[A-Z0-9_]+$")
BOOTH_NUMBER_RE = re.compile(r"^[A-Z0-9]+$")


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("request body must be a JSON object")
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def require(data, name):
    if not _present(data, name):
        bad("%s is required" % name)
    return data[name]


def integer(data, name, minimum=None, maximum=None, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s" % (name, maximum))
    return value


def number(data, name, minimum=None, maximum=None, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s" % (name, maximum))
    return value


def text(data, name, min_len=1, max_len=None, required=True, default=None, pattern=None):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    if pattern is not None and not pattern.match(value):
        bad("%s has an invalid format" % name)
    return value


def enum(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def boolean(data, name, required=False, default=False):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def email(data, name, max_len=254, required=True):
    value = text(data, name, min_len=1, max_len=max_len, required=required)
    if value is None:
        return None
    if value.count("@") != 1:
        bad("%s must contain exactly one @" % name)
    return value


def id_list(data, name, required=True, allow_empty=False, max_len=None):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return None
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    for item in value:
        if not isinstance(item, str) or not item:
            bad("%s must contain non-empty strings" % name)
    if not value and not allow_empty:
        bad("%s must not be empty" % name)
    if max_len is not None and len(value) > max_len:
        bad("%s must contain at most %d entries" % (name, max_len))
    if len(set(value)) != len(value):
        bad("%s must not contain duplicates" % name)
    return value


def code_list(data, name, min_len=1, max_len=8, required=True):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return None
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if len(value) < min_len or len(value) > max_len:
        bad("%s must contain between %d and %d entries" % (name, min_len, max_len))
    for item in value:
        if not isinstance(item, str) or not (1 <= len(item) <= 32) or not CODE_RE.match(item):
            bad("%s entries must be uppercase codes" % name)
    if len(set(value)) != len(value):
        bad("%s must not contain duplicate entries" % name)
    return value


def date_field(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 date" % name)
    parsed = parse_date(value)
    if parsed is None:
        bad("%s must be an ISO 8601 date" % name)
    return parsed


def datetime_field(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 timestamp" % name)
    parsed = parse_dt(value)
    if parsed is None:
        bad("%s must be an ISO 8601 timestamp" % name)
    return parsed


def fee_schedule(data, name, required=True, default=None):
    """1-6 buckets of {min_days_out, pct}, distinct days, exactly one zero."""
    if not _present(data, name):
        if required:
            bad("%s is required" % name)
        return default
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if len(value) < 1 or len(value) > 6:
        bad("%s must contain between 1 and 6 buckets" % name)
    buckets = []
    for entry in value:
        if not isinstance(entry, dict):
            bad("%s entries must be objects" % name)
        days = integer(entry, "min_days_out", minimum=0)
        pct = number(entry, "pct", minimum=0, maximum=100)
        buckets.append({"min_days_out": days, "pct": pct})
    days_values = [b["min_days_out"] for b in buckets]
    if len(set(days_values)) != len(days_values):
        bad("%s buckets must have distinct min_days_out values" % name)
    if days_values.count(0) != 1:
        bad("%s must contain exactly one bucket with min_days_out 0" % name)
    return buckets


def normalize_number(value):
    """Emit whole numbers as ints so JSON stays clean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value

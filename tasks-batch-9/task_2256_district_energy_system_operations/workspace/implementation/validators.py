"""Input schema validation (admission ladder step 3, ERR_INVALID_REQUEST)."""

import json

from flask import request

from db import parse_dt
from errors import fail


def bad(message):
    fail("ERR_INVALID_REQUEST", message)


def json_body():
    """Parsed JSON object body; an absent or blank body reads as {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        bad("request body is not valid JSON")
    if not isinstance(data, dict):
        bad("request body must be a JSON object")
    return data


def present(body, name):
    """A field counts as supplied only when present and not explicitly null."""
    return name in body and body[name] is not None


def get_str(body, name, required=True, default=None, min_len=1, max_len=None):
    if not present(body, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("field '%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("field '%s' must be at most %d characters" % (name, max_len))
    return value


def get_num(body, name, required=True, default=None, gt=None, ge=None, le=None):
    if not present(body, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("field '%s' must be a number" % name)
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        bad("field '%s' must be a finite number" % name)
    if gt is not None and not value > gt:
        bad("field '%s' must be greater than %s" % (name, gt))
    if ge is not None and not value >= ge:
        bad("field '%s' must be at least %s" % (name, ge))
    if le is not None and not value <= le:
        bad("field '%s' must be at most %s" % (name, le))
    return value


def get_int(body, name, required=True, default=None, gt=None, ge=None, le=None):
    if not present(body, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool):
        bad("field '%s' must be an integer" % name)
    if isinstance(value, float):
        if value != int(value):
            bad("field '%s' must be an integer" % name)
        value = int(value)
    if not isinstance(value, int):
        bad("field '%s' must be an integer" % name)
    if gt is not None and not value > gt:
        bad("field '%s' must be greater than %s" % (name, gt))
    if ge is not None and not value >= ge:
        bad("field '%s' must be at least %s" % (name, ge))
    if le is not None and not value <= le:
        bad("field '%s' must be at most %s" % (name, le))
    return value


def get_bool(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("field '%s' must be a boolean" % name)
    return value


def get_enum(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            bad("field '%s' is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def get_dt(body, name, required=True, default=None):
    """Returns (raw_string, datetime) so the caller can echo the client's text."""
    if not present(body, name):
        if required:
            bad("field '%s' is required" % name)
        return default, None
    value = body[name]
    if not isinstance(value, str):
        bad("field '%s' must be an ISO 8601 datetime string" % name)
    try:
        parsed = parse_dt(value)
    except (ValueError, TypeError):
        bad("field '%s' must be an ISO 8601 datetime string" % name)
    return value, parsed


def get_tiers(body, name="tiers", required=True):
    """Tier ladder: non-empty, strictly increasing load_factor_max."""
    if not present(body, name):
        if required:
            bad("field '%s' is required" % name)
        return None
    value = body[name]
    if not isinstance(value, list) or len(value) == 0:
        bad("field '%s' must be a non-empty array" % name)
    tiers = []
    previous = None
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            bad("each entry of '%s' must be an object" % name)
        ceiling = get_num(item, "load_factor_max", required=True)
        rate = get_num(item, "energy_rate_per_mwh", required=True)
        if previous is not None and not ceiling > previous:
            bad("tier load_factor_max values must be strictly increasing")
        previous = ceiling
        tiers.append({"load_factor_max": ceiling, "energy_rate_per_mwh": rate})
        del index
    return tiers


def query_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        bad("query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def query_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)

"""Request-shape validation helpers (PRD section 2.5 tier 3)."""

from flask import request

import config
from errors import ApiError
from store import parse_dt

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """Return the JSON body as a dict; a missing or empty body yields {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        bad("Request body must be valid JSON.")
    if not isinstance(body, dict):
        bad("Request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


def v_string(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-empty string." % name)
    return value


def v_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %d." % (name, maximum))
    return value


def v_bool(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def v_datetime(body, name, required=True, default=None):
    """Validate an ISO-8601 datetime input and return the raw string as supplied."""
    if not present(body, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 datetime string." % name)
    try:
        parse_dt(value)
    except Exception:
        bad("Field '%s' must be an ISO 8601 datetime string." % name)
    return value


# ------------------------------------------------------------ query strings --


def q_pagination():
    limit = config.PAGE_LIMIT_DEFAULT
    offset = config.PAGE_OFFSET_DEFAULT
    args = request.args
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("limit must be an integer between 1 and 100.")
        if limit < config.PAGE_LIMIT_MIN or limit > config.PAGE_LIMIT_MAX:
            bad("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("offset must be a non-negative integer.")
        if offset < 0:
            bad("offset must be a non-negative integer.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value.strip() == "":
        bad("Query parameter '%s' must not be empty." % name)
    return value


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value

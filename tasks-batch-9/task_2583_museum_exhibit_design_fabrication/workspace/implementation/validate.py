"""Request-body shape validation — ladder step 4 (ERR_INVALID_REQUEST)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body_object(required=True):
    """Parse the JSON body; must be a JSON object when a body is expected."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            bad("A JSON object body is required.")
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("The request body is not parseable JSON.")
    if parsed is None:
        if required:
            bad("A JSON object body is required.")
        return {}
    if not isinstance(parsed, dict):
        bad("The request body must be a JSON object.")
    return parsed


def _fetch(body, key, required, default):
    if key not in body or body.get(key, None) is None:
        if required:
            bad("Field '%s' is required and must not be null." % key)
        return MISSING if default is MISSING else default
    return body[key]


def v_str(body, key, min_len=None, max_len=None, required=True, non_blank=False, default=None):
    value = _fetch(body, key, required, default)
    if value is default and (key not in body or body.get(key, None) is None):
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if non_blank and value.strip() == "":
        bad("Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def v_enum(body, key, allowed, required=True, default=None):
    value = _fetch(body, key, required, default)
    if value is default and (key not in body or body.get(key, None) is None):
        return value
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def v_int(body, key, minimum=None, maximum=None, required=True, default=None):
    value = _fetch(body, key, required, default)
    if value is default and (key not in body or body.get(key, None) is None):
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (key, maximum))
    return value


def v_num(body, key, gt=None, ge=None, lt=None, le=None, required=True, default=None):
    value = _fetch(body, key, required, default)
    if value is default and (key not in body or body.get(key, None) is None):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        bad("Field '%s' must be a finite number." % key)
    if gt is not None and not value > gt:
        bad("Field '%s' must be greater than %s." % (key, gt))
    if ge is not None and not value >= ge:
        bad("Field '%s' must be at least %s." % (key, ge))
    if lt is not None and not value < lt:
        bad("Field '%s' must be less than %s." % (key, lt))
    if le is not None and not value <= le:
        bad("Field '%s' must be at most %s." % (key, le))
    return value


def v_bool(body, key, required=True, default=None):
    value = _fetch(body, key, required, default)
    if value is default and (key not in body or body.get(key, None) is None):
        return value
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def parse_datetime(value, key):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC datetime string." % key)
    text = value.strip()
    if text == "":
        bad("Field '%s' must be an ISO 8601 UTC datetime string." % key)
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 UTC datetime string." % key)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def v_datetime(body, key, required=True, default=None):
    value = _fetch(body, key, required, default)
    if value is default and (key not in body or body.get(key, None) is None):
        return value
    return parse_datetime(value, key)


def v_id(body, key, required=True, default=None):
    value = _fetch(body, key, required, default)
    if value is default and (key not in body or body.get(key, None) is None):
        return value
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-blank identifier string." % key)
    return value


OBJECTIVE_CODE_RE = re.compile(r"^OBJ-[A-Z0-9]{2,6}$")


def v_objective_codes(body, key):
    value = _fetch(body, key, True, None)
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    if len(value) < 2 or len(value) > 8:
        bad("Field '%s' must hold between 2 and 8 codes." % key)
    for item in value:
        if not isinstance(item, str) or not OBJECTIVE_CODE_RE.match(item):
            bad("Each objective code must match OBJ- followed by 2 to 6 uppercase letters or digits.")
    if len(set(value)) != len(value):
        bad("Objective codes must be unique.")
    return list(value)


def v_string_list(body, key):
    value = _fetch(body, key, True, None)
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    return value

"""Schema validation — validation priority 3, ERR_INVALID_REQUEST / 400."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_RE = re.compile(r"^[+-]?\d+$")


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def _present(body, key, required, default):
    if key not in body or body[key] is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return False, default
    return True, body[key]


def string(body, key, required=True, default=None, allow_empty=True):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        raise bad("Field '%s' must not be empty." % key)
    return value


def integer(body, key, required=True, default=None, minimum=None, maximum=None):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be at most %d." % (key, maximum))
    return value


def boolean(body, key, required=True, default=None):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def enum(body, key, allowed, required=True, default=None):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def date_field(body, key, required=True, default=None):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise bad("Field '%s' must be an ISO 8601 calendar date." % key)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 calendar date." % key)


def instant_field(body, key, required=True, default=None):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    return parse_instant(value, key)


def parse_instant(value, key):
    if not isinstance(value, str):
        raise bad("Field '%s' must be an ISO 8601 timestamp." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 timestamp." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def string_array(body, key, required=True, default=None, non_empty=False, distinct=False, allowed=None):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            raise bad("Field '%s' must be an array of strings." % key)
        if allowed is not None and item not in allowed:
            raise bad("Field '%s' contains a value outside its declared set." % key)
    if non_empty and len(value) == 0:
        raise bad("Field '%s' must not be empty." % key)
    if distinct and len(set(value)) != len(value):
        raise bad("Field '%s' must not contain duplicates." % key)
    return value


def object_array(body, key, required=True, default=None, non_empty=False):
    found, value = _present(body, key, required, default)
    if not found:
        return value
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, dict):
            raise bad("Field '%s' must be an array of objects." % key)
    if non_empty and len(value) == 0:
        raise bad("Field '%s' must not be empty." % key)
    return value


# ------------------------------------------------------------------ pagination

def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            raise bad("Query parameter 'limit' must be an integer.")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset.strip()):
            raise bad("Query parameter 'offset' must be an integer.")
        offset = int(raw_offset)
        if offset < 0:
            raise bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_filter(name, allowed=None):
    value = request.args.get(name)
    if value is None:
        return None
    if allowed is not None and value not in allowed:
        raise bad("Query parameter '%s' carries a value outside its declared set." % name)
    return value

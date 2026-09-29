"""Authentication / authorization and request-shape helpers (PRD 2.1, 2.3, 2.11)."""

import datetime
import json

from flask import request

from constants import (
    ALL_ROLES,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
)
from errors import ApiError


# ---------------------------------------------------------------------------
# 1. Authentication -> 2. Authorization (always before any body inspection)
# ---------------------------------------------------------------------------
def authorize(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    return user_id, role


# ---------------------------------------------------------------------------
# 3. Request shape
# ---------------------------------------------------------------------------
def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    raw = request.get_data() or b""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, allow_empty=False):
    if not _present(body, field):
        raise bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % field)
    if not allow_empty and not value.strip():
        raise bad("Field '%s' must be a non-empty string." % field)
    return value


def opt_str(body, field, default=None, allow_empty=True):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % field)
    if not allow_empty and not value.strip():
        raise bad("Field '%s' must be a non-empty string." % field)
    return value


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        raise bad("Field '%s' must be one of: %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if not _present(body, field):
        return default
    value = req_str(body, field)
    if value not in allowed:
        raise bad("Field '%s' must be one of: %s." % (field, ", ".join(allowed)))
    return value


def _check_int(field, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %d." % (field, maximum))
    return value


def req_int(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        raise bad("Field '%s' is required." % field)
    return _check_int(field, body[field], minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if not _present(body, field):
        return default
    return _check_int(field, body[field], minimum, maximum)


def opt_bool(body, field, default=None):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % field)
    return value


def req_id(body, field):
    return req_str(body, field)


def opt_id(body, field):
    if not _present(body, field):
        return None
    return req_str(body, field)


def req_list(body, field, item_type=str):
    if not _present(body, field):
        raise bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % field)
    for item in value:
        if item_type is str and (not isinstance(item, str) or not item.strip()):
            raise bad("Field '%s' must contain non-empty strings." % field)
    return value


def opt_list(body, field, default=None, item_type=str):
    if not _present(body, field):
        return [] if default is None else default
    return req_list(body, field, item_type)


def req_int_map(body, field, allowed_keys=None, allow_empty=False):
    if not _present(body, field):
        raise bad("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, dict):
        raise bad("Field '%s' must be an object." % field)
    if not allow_empty and not value:
        raise bad("Field '%s' must not be empty." % field)
    out = {}
    for key, item in value.items():
        if allowed_keys is not None and key not in allowed_keys:
            raise bad("Field '%s' has an unknown key '%s'." % (field, key))
        if isinstance(item, bool) or not isinstance(item, int):
            raise bad("Field '%s' values must be integers." % field)
        if item < 0:
            raise bad("Field '%s' values must be non-negative." % field)
        out[key] = item
    return out


def opt_int_map(body, field, allowed_keys=None, default=None):
    if not _present(body, field):
        return dict(default) if default else {}
    return req_int_map(body, field, allowed_keys, allow_empty=True)


def opt_enum_list(body, field, allowed, default=None):
    if not _present(body, field):
        return list(default) if default else []
    value = req_list(body, field)
    for item in value:
        if item not in allowed:
            raise bad("Field '%s' must contain only: %s." % (field, ", ".join(allowed)))
    return value


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def parse_date_value(field, value):
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % field)
    text = value.strip()
    try:
        return datetime.date.fromisoformat(text[:10])
    except Exception:
        raise bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % field)


def req_date(body, field):
    if not _present(body, field):
        raise bad("Field '%s' is required." % field)
    parse_date_value(field, body[field])
    return body[field]


def opt_date(body, field, default=None):
    if not _present(body, field):
        return default
    parse_date_value(field, body[field])
    return body[field]


def as_date(field, raw):
    return parse_date_value(field, raw)


def parse_instant(field, value):
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be an ISO 8601 instant." % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except Exception:
        try:
            parsed = datetime.datetime.combine(
                datetime.date.fromisoformat(text), datetime.time()
            )
        except Exception:
            raise bad("Field '%s' must be an ISO 8601 instant." % field)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------
def pagination():
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except Exception:
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise bad(
                "Query parameter 'limit' must be between %d and %d."
                % (MIN_LIMIT, MAX_LIMIT)
            )
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except Exception:
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad("Query parameter '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_req_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        raise bad("Query parameter '%s' is required." % name)
    if raw not in allowed:
        raise bad("Query parameter '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return raw


def query_req_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        raise bad("Query parameter '%s' is required." % name)
    return raw


def query_int(name, default=None, minimum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except Exception:
        raise bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("Query parameter '%s' must be >= %d." % (name, minimum))
    return value


def query_req_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        raise bad("Query parameter '%s' is required." % name)
    return parse_date_value(name, raw)

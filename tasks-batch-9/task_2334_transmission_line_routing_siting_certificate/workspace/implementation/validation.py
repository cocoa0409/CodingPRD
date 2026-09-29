"""Payload shape checks, path/reference resolution and pagination parsing."""

from datetime import datetime, timezone

from flask import request

from db import by_created
from errors import ApiError

MISSING = object()


# --------------------------------------------------------------- body ----
def get_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _present(body, key):
    return key in body and body[key] is not None


def bad(key, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, detail))


def req_str(body, key):
    if not _present(body, key):
        bad(key, "is required")
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        bad(key, "must be a non-empty string")
    return value


def opt_str(body, key, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        bad(key, "must be a string")
    return value


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        bad(key, "is required")
    value = body[key]
    if not _is_int(value):
        bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(key, "must be <= %s" % maximum)
    return value


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        return default
    return req_int(body, key, minimum, maximum)


def req_num(body, key, minimum=None, maximum=None, exclusive_min=None):
    if not _present(body, key):
        bad(key, "is required")
    value = body[key]
    if not _is_num(value):
        bad(key, "must be a number")
    if exclusive_min is not None and value <= exclusive_min:
        bad(key, "must be > %s" % exclusive_min)
    if minimum is not None and value < minimum:
        bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(key, "must be <= %s" % maximum)
    return value


def req_bool(body, key):
    if not _present(body, key):
        bad(key, "is required")
    value = body[key]
    if not isinstance(value, bool):
        bad(key, "must be a boolean")
    return value


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, bool):
        bad(key, "must be a boolean")
    return value


def parse_dt(value, key):
    if not isinstance(value, str) or value.strip() == "":
        bad(key, "must be an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad(key, "must be an ISO 8601 timestamp string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(body, key):
    if not _present(body, key):
        bad(key, "is required")
    return parse_dt(body[key], key)


def opt_dt(body, key, default=None):
    if not _present(body, key):
        return default
    return parse_dt(body[key], key)


def req_id(body, key):
    if not _present(body, key):
        bad(key, "is required")
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        bad(key, "must be a non-empty string")
    return value


def opt_id(body, key):
    if not _present(body, key):
        return None
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        bad(key, "must be a non-empty string")
    return value


def must_be_absent(body, key, reason):
    if _present(body, key):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be null %s." % (key, reason))


# ------------------------------------------------------ id resolution ----
def find_path(collection, row_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such resource: %s." % row_id)
    return row


def find_ref(collection, row_id, label="reference"):
    row = collection.get(row_id)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "Referenced %s %s does not exist." % (label, row_id))
    return row


def fk(body, key, collection, label=None):
    """Resolve a body FK when supplied (priority 4); shape checks come later."""
    if not _present(body, key):
        return None
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        return None
    return find_ref(collection, value, label or key)


# --------------------------------------------------------- pagination ----
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def paginate(rows):
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    total = len(rows)
    window = rows[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, pagination


def apply_filters(rows, fields):
    out = rows
    for field in fields:
        value = request.args.get(field)
        if value is None or value == "":
            continue
        out = [r for r in out if str(r.get(field)) == value]
    return out


def collection_list(collection, filters, sort_key=None):
    rows = list(collection.values())
    rows = apply_filters(rows, filters)
    rows = by_created(rows) if sort_key is None else sorted(rows, key=sort_key)
    return paginate(rows)

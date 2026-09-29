"""Request shape, pagination and path/body resolution helpers.

Ordering of the checks themselves lives in the route handlers, which follow the
fixed judgement order of PRD 2.5.
"""

from flask import request

import clock
import db
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def invalid(message="The request payload is invalid."):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    body = request.get_json(force=True, silent=True)
    if body is None:
        raise invalid("Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise invalid("Request body must be a JSON object.")
    return body


def present(body, name):
    return name in body and body[name] is not None


def v_string(body, name, required=True, default=None, min_len=None, max_len=None):
    if not present(body, name):
        if required:
            raise invalid("'%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise invalid("'%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise invalid("'%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("'%s' must be at most %d characters." % (name, max_len))
    return value


def v_int(body, name, required=True, default=None, minimum=None, maximum=None, choices=None):
    if not present(body, name):
        if required:
            raise invalid("'%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("'%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("'%s' must be <= %s." % (name, maximum))
    if choices is not None and value not in choices:
        raise invalid("'%s' must be one of %s." % (name, sorted(choices)))
    return value


def v_bool(body, name, required=False, default=False):
    if not present(body, name):
        if required:
            raise invalid("'%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean." % name)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            raise invalid("'%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("'%s' must be one of %s." % (name, sorted(allowed)))
    return value


def v_array(body, name, item="string", required=True, default=None, choices=None):
    """Arrays are non-empty and free of duplicates (PRD 2.5 step 7)."""
    if not present(body, name):
        if required:
            raise invalid("'%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, list):
        raise invalid("'%s' must be an array." % name)
    if len(value) == 0:
        raise invalid("'%s' must not be empty." % name)
    for element in value:
        if item == "string":
            if not isinstance(element, str):
                raise invalid("'%s' must contain strings only." % name)
        elif item == "integer":
            if isinstance(element, bool) or not isinstance(element, int):
                raise invalid("'%s' must contain integers only." % name)
        if choices is not None and element not in choices:
            raise invalid("'%s' contains an unsupported value." % name)
    if len(set(value)) != len(value):
        raise invalid("'%s' must not contain duplicates." % name)
    return list(value)


def v_datetime(body, name, required=True):
    """Returns (raw_string, datetime). Client supplied instants echo verbatim."""
    if not present(body, name):
        if required:
            raise invalid("'%s' is required." % name)
        return None, None
    value = body[name]
    parsed = clock.parse(value)
    if parsed is None:
        raise invalid("'%s' must be an ISO 8601 UTC instant." % name)
    return value, parsed


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise invalid("'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("'offset' must be an integer.")
        if offset < 0:
            raise invalid("'offset' must not be negative.")
    return limit, offset


def paginate(rows):
    """Window a list of rows already in their default order."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return db.serialize_many(window), meta


def path_lookup(collection, identifier, error_id):
    """Path existence, resolved left to right (PRD 2.5 step 3)."""
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def body_lookup(collection, identifier, error_id):
    """Body reference existence (PRD 2.5 step 4)."""
    record = collection.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(error_id)
    return record

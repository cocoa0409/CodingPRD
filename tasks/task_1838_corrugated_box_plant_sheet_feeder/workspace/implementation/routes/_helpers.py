"""Shared helpers: pagination, JSON body parsing."""
from flask import request

from errors import err_invalid_request
from response import success_list


def get_json_body():
    """Return parsed JSON body or raise 400."""
    if not request.is_json:
        if request.data in (b"", None):
            return {}
        raise err_invalid_request("Request body must be JSON")
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise err_invalid_request("Malformed JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    return body


def parse_pagination():
    """Parse limit/offset with defaults and bounds; raise 400 on invalid."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range [1,100]")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate_list(items, serializer, filters=None):
    """Sort by created_at ASC, apply equality filters, paginate, return response."""
    filtered = items
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            filtered = [x for x in filtered if _matches(x, key, val)]
    filtered.sort(key=lambda x: x["created_at"])
    total = len(filtered)
    limit, offset = parse_pagination()
    page = filtered[offset:offset + limit]
    return success_list([serializer(x) for x in page], total, limit, offset)


def _matches(entity, key, value):
    """Compare entity field with string query param."""
    v = entity.get(key)
    if v is None:
        return False
    if isinstance(v, bool):
        return (str(value).lower() == "true") == v
    if isinstance(v, int):
        try:
            return v == int(value)
        except (TypeError, ValueError):
            return False
    return str(v) == value


def require_fields(body, fields):
    """Ensure each required field is present and not None."""
    for f in fields:
        if f not in body:
            raise err_invalid_request(f"Missing required field: {f}")
        if body[f] is None:
            raise err_invalid_request(f"Field cannot be null: {f}")

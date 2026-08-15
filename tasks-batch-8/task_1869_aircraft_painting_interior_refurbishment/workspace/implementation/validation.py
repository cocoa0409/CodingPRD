"""Request-body validation helpers (validations priority 3: ERR_INVALID_REQUEST)."""
from flask import request

from db import parse_dt
from errors import bad_request


def get_body(required=False):
    """Return the JSON request body as a dict.

    Endpoints with no declared inputs tolerate an absent/empty body; endpoints
    with required inputs reject an absent or non-object body with 400.
    """
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise bad_request("Request body must be a valid JSON object")
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def _type_ok(value, kind):
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "num":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "datetime":
        return parse_dt(value) is not None
    return True


def field(data, name, kind="str", required=True, enum=None, default=None):
    """Extract and type/enum-check a body field.

    Missing required fields and type/enum violations -> ERR_INVALID_REQUEST.
    Datetime fields are returned as aware UTC datetimes.
    """
    if name not in data or data[name] is None:
        if required:
            raise bad_request(f"Missing required field: {name}")
        return default
    value = data[name]
    if not _type_ok(value, kind):
        raise bad_request(f"Field {name} has an invalid type or value")
    if enum is not None and value not in enum:
        raise bad_request(f"Field {name} must be one of {sorted(enum)}")
    if kind == "datetime":
        return parse_dt(value)
    return value


def pagination_params():
    """Read limit/offset query params with scaffold defaults (10 / 0, 1..100)."""
    def _int(raw, fallback):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return fallback

    limit = _int(request.args.get("limit"), 10)
    offset = _int(request.args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, serializer=None):
    """Sort-free pagination: items must already be in response order."""
    from response import success_list

    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    if serializer is not None:
        page = [serializer(x) for x in page]
    return success_list(page, total, limit, offset)

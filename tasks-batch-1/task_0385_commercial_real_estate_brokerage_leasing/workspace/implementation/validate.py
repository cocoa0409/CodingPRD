"""Body parsing and field-constraint validation helpers (PRD §2.9)."""
from flask import request

from errors import err


def parse_body():
    """Parse JSON body. Malformed JSON -> ERR_VALIDATION (HTTP 400) (PRD §2.9).

    An absent body is treated as an empty object (action endpoints often
    have no body).
    """
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Malformed JSON request body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def check_str_type(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return None
    if not is_str(body[field]):
        raise err("ERR_VALIDATION", f"Field {field} must be a string")
    return body[field]


def check_int_type(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    if not is_int(body[field]):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer")
    return body[field]


def check_number_type(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    if not is_number(body[field]):
        raise err("ERR_VALIDATION", f"Field {field} must be a number")
    return body[field]


def check_bool_type(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    if not isinstance(body[field], bool):
        raise err("ERR_VALIDATION", f"Field {field} must be a boolean")
    return body[field]


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Out-of-range -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (seq tiebreak), then slice (PRD §2.3)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total

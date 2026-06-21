"""Shared validation helpers: pagination, body parsing, existence checks."""
from flask import request

from errors import ApiError


def get_json_body():
    """Return the request JSON body as a dict, or {} when absent/empty.

    A malformed (non-dict / unparseable) body is ERR_INVALID_REQUEST.
    """
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return data
    return {}


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). limit default 10 [1,100];
    offset default 0 [0,inf). Out-of-range / non-integer -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by creation order and return (page, total_count)."""
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def require_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a string" % field)
    if not allow_empty and v.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % field)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return v


def present(body, field):
    return field in body and body[field] is not None

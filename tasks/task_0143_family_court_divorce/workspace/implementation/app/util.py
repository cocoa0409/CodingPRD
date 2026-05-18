"""Small request-parsing helpers shared across routes."""
from flask import request

from app.errors import ApiError


def get_json_body():
    """Return the JSON body as a dict; tolerate missing or empty body."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        # Treat malformed JSON as an invalid request body.
        raise ApiError("ERR_INVALID_STATE", 409, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_STATE", 409, "Request body must be a JSON object")
    return body


def pagination_args():
    """Return (limit, offset) from query string per PRD §2.3."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, limit, offset, sort_key="created_at"):
    """Sort by sort_key ascending and slice; return (items, total_count)."""
    sorted_list = sorted(records, key=lambda r: r.get(sort_key))
    total = len(sorted_list)
    return sorted_list[offset : offset + limit], total

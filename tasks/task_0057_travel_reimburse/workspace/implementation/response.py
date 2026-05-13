"""Response envelope helpers matching PRD §2.2."""

from __future__ import annotations

from flask import jsonify, request

from utils import CLOCK, new_request_id


def _meta(pagination: dict | None = None) -> dict:
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": CLOCK.now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, status: int = 200, pagination: dict | None = None,
            response_type: str | None = None):
    """Wrap successful 2xx response."""
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    payload = {
        "meta": _meta(pagination=pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(payload)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, http_status: int):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(payload)
    resp.status_code = http_status
    return resp


def empty_204():
    """204 No Content with empty body (per PRD: DELETE item returns 204 empty)."""
    resp = jsonify(None)
    resp.set_data(b"")
    resp.status_code = 204
    return resp


# ---------------- Pagination helpers ----------------
def parse_pagination():
    """Read & validate `limit`/`offset` per §2.3. Returns (limit, offset).

    Raises APIError(ERR_VALIDATION) on out-of-range values.
    """
    from errors import APIError, ERR_VALIDATION

    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)

    limit = 10
    offset = 0

    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_VALIDATION, "limit must be an integer", 422)
        if limit < 1 or limit > 100:
            raise APIError(ERR_VALIDATION, "limit must be between 1 and 100", 422)

    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_VALIDATION, "offset must be an integer", 422)
        if offset < 0:
            raise APIError(ERR_VALIDATION, "offset must be >= 0", 422)

    return limit, offset


def paginate(rows: list, limit: int, offset: int):
    """Slice rows, return (page, pagination_meta dict)."""
    total = len(rows)
    page = rows[offset : offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta

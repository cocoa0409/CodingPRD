"""Response envelope helpers per PRD §2.2 / SCAFFOLD response_envelope."""
import uuid

from flask import jsonify, request

import store
from errors import ApiError, err_invalid_request


def _request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, code=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_body():
    """Return the JSON request body as a dict; {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def paginate(items):
    """Apply limit/offset query params to a pre-sorted list.

    Returns (page, pagination_meta). limit defaults to 10 (min 1, max 100),
    offset defaults to 0.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def list_response(items, code=200):
    page, meta = paginate(items)
    return success(page, code=code, pagination=meta)


def sort_created(items):
    """Default list ordering: created_at ascending (stable by insertion seq)."""
    return sorted(items, key=lambda e: (e.get("created_at") or "", e.get("_seq", 0)))


def serialize(entity):
    """Strip internal bookkeeping fields from a stored entity."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}

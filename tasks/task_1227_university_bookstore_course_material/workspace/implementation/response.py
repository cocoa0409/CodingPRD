"""Response envelope (PRD §2.2 / SCAFFOLD response_envelope).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""

import uuid

from flask import jsonify

from db import store, fmt_dt, pub
from middleware import pagination


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_dt(store.clock),
    }


def success(data, status=200, response_type="object", page=None):
    meta = _meta()
    if page is not None:
        meta.update(page)
    return jsonify({
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }), status


def error_response(error_id, http_status, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status


def list_response(items):
    """Paginated array envelope. Items are store dicts; sorted by created_at
    ascending (stable sort keeps insertion order as the tiebreak)."""
    limit, offset = pagination()
    ordered = sorted(items, key=lambda e: e["created_at"])
    total = len(ordered)
    page_items = ordered[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page_items)) < total,
    }
    return success([pub(e) for e in page_items], status=200,
                   response_type="array", page=page)

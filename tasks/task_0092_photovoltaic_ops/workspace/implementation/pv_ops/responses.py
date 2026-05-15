"""Response envelope helpers."""
from __future__ import annotations

from typing import Any, Optional

from flask import current_app, jsonify

from pv_ops.store import new_request_id


def _now_iso() -> str:
    store = current_app.extensions["store"]
    return store.clock.now_iso()


def build_success_envelope(
    data: Any,
    response_type: str = "object",
    pagination: Optional[dict] = None,
) -> dict:
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        # `limit`, `offset`, `total_count`, `has_more`
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return body


def build_error_envelope(error_id: str, message: str) -> dict:
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": _now_iso(),
    }
    return {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }


def success(data: Any, code: int = 200):
    return jsonify(build_success_envelope(data, response_type="object")), code


def created(data: Any):
    return jsonify(build_success_envelope(data, response_type="object")), 201


def accepted(data: Any):
    return jsonify(build_success_envelope(data, response_type="object")), 202


def listed(data: list, *, limit: int, offset: int, total_count: int, has_more: bool, code: int = 200):
    body = build_success_envelope(
        data,
        response_type="array",
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
    )
    return jsonify(body), code

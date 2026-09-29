"""Standard response envelope (PRD section 2.2)."""
from __future__ import annotations

from flask import jsonify

import util


def _meta(clock_iso: str) -> dict:
    return {
        "api_request_id": util.request_id(),
        "api_request_timestamp": clock_iso,
    }


def ok(data, status: int, clock_iso: str):
    body = {
        "meta": _meta(clock_iso),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit: int, offset: int, total: int, clock_iso: str):
    meta = _meta(clock_iso)
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err(error_id: str, message: str, status: int, clock_iso: str):
    body = {
        "meta": _meta(clock_iso),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

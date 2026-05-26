"""Response envelope helpers — matches SCAFFOLD §1.0 / PRD §2.2 verbatim."""
from __future__ import annotations

from typing import Any

from flask import jsonify

import db


def _meta() -> dict[str, Any]:
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.fmt_ts(db.utcnow()),
    }


def ok(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_ok(items: list[Any], limit: int, offset: int, total_count: int, status: int = 200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + limit < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status

"""Standard response envelope helpers (PRD §2.2)."""

from __future__ import annotations

import uuid

from flask import jsonify

import db


def _meta() -> dict:
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.fmt_ts(db.utcnow()),
    }


def success_object(data: dict, status: int = 200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(payload), status


def success_list(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(payload), status


def error_payload(error_id: str, message: str) -> dict:
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }

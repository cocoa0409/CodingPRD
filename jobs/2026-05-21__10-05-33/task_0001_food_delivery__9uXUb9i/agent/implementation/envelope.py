"""Standard success/error envelope helpers (PRD §2.2)."""
from __future__ import annotations

from typing import Any
from flask import jsonify, g

from store import gen_request_id, iso_z, now


def _meta(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rid = getattr(g, "request_id", None) or gen_request_id()
    ts = getattr(g, "request_ts", None) or iso_z(now())
    meta = {"api_request_id": rid, "api_request_timestamp": ts}
    if extra:
        meta.update(extra)
    return meta


def success(data: Any, status: int = 200, *, list_meta: dict[str, Any] | None = None):
    if isinstance(data, list):
        body = {
            "meta": _meta(list_meta),
            "response_type": "array",
            "data": data,
        }
    else:
        body = {
            "meta": _meta(),
            "response_type": "object",
            "data": data if data is not None else {},
        }
    return jsonify(body), status


def error(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

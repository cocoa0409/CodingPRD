"""Response envelope helpers per PRD §2.2."""
from __future__ import annotations

import secrets
import string
from flask import jsonify

from db import now_iso, db


ALPHABET = string.ascii_letters + string.digits


def _request_id() -> str:
    return "req_" + "".join(secrets.choice(ALPHABET) for _ in range(20))


def _meta(pagination: dict | None = None) -> dict:
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(db.clock),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_response(items, limit: int, offset: int, total_count: int):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status

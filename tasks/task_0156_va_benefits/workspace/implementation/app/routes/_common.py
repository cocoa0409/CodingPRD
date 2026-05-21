"""Shared helpers for route modules."""
from __future__ import annotations

from typing import Any

from flask import current_app, g, jsonify, request

from ..envelope import array_envelope, object_envelope
from ..errors import ApiError
from ..store import Store


def get_store() -> Store:
    return current_app.config["STORE"]


def get_json_body() -> dict:
    """Return parsed JSON body; missing body → empty dict."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_BODY", "request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    return body


def respond_object(data: Any, status: int = 200):
    return jsonify(object_envelope(data)), status


def respond_array(items: list[Any], *, limit: int, offset: int, total_count: int, status: int = 200):
    return jsonify(array_envelope(items, limit=limit, offset=offset, total_count=total_count)), status

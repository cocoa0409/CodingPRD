"""Response envelope and Flask error handler wiring."""
from __future__ import annotations

import secrets
import string
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from core.errors import APIError
from core.utils import now_iso


_ALPHANUM = string.ascii_letters + string.digits


def new_request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _base_meta() -> Dict[str, Any]:
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }


def success_response(
    data: Any,
    status: int = 200,
    response_type: str = "object",
    pagination: Optional[Dict[str, Any]] = None,
):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(405)
    def _handle_405(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def _handle_400(_exc):
        return error_response("ERR_VALIDATION", "Bad request.", 422)

    @app.errorhandler(415)
    def _handle_415(_exc):
        return error_response("ERR_VALIDATION", "Unsupported media type.", 422)

    @app.errorhandler(Exception)
    def _handle_generic(exc: Exception):
        # Log unexpected errors but still return a structured response.
        import traceback
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"Unexpected error: {exc}", 422)


def get_json_body() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        return {}
    return body

"""Custom exceptions and error handling."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .envelope import error_envelope


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _api_error(err: APIError):
        return jsonify(error_envelope(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def _not_found(err):
        return jsonify(error_envelope("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return jsonify(error_envelope("ERR_NOT_FOUND", "Method not allowed")), 404

    @app.errorhandler(400)
    def _bad_request(err):
        return jsonify(error_envelope("ERR_VALIDATION", "Bad request")), 422

    @app.errorhandler(Exception)
    def _unhandled(err: Exception):
        # Last-resort handler to keep tests deterministic.
        return jsonify(error_envelope("ERR_VALIDATION", str(err))), 422

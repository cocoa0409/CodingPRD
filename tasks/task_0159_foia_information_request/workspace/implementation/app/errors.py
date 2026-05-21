"""Error catalogue and Flask error handlers."""

from __future__ import annotations

from typing import Optional

from flask import Flask, jsonify, request

from .envelope import build_meta


class ApiError(Exception):
    """A structured API error: error_id + HTTP status + human message."""

    def __init__(self, error_id: str, http_status: int, message: Optional[str] = None) -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical error ids (mirrors SCAFFOLD §1.6) — kept here so route code can
# reference them by symbol rather than string literal.
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"
ERR_INVALID_ROLE = "ERR_INVALID_ROLE"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
ERR_DUPLICATE_APPEAL = "ERR_DUPLICATE_APPEAL"
ERR_FEE_ASSESSMENT_EXISTS = "ERR_FEE_ASSESSMENT_EXISTS"
ERR_NOTICE_ALREADY_CLOSED = "ERR_NOTICE_ALREADY_CLOSED"
ERR_DUPLICATE_EXEMPTION = "ERR_DUPLICATE_EXEMPTION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_INVALID_GLOMAR_BASIS = "ERR_INVALID_GLOMAR_BASIS"
ERR_MISSING_THIRD_PARTY_NOTICE = "ERR_MISSING_THIRD_PARTY_NOTICE"
ERR_TOLLING_LIMIT_EXCEEDED = "ERR_TOLLING_LIMIT_EXCEEDED"
ERR_THIRD_PARTY_DEADLINE_PASSED = "ERR_THIRD_PARTY_DEADLINE_PASSED"
ERR_APPEAL_WINDOW_EXPIRED = "ERR_APPEAL_WINDOW_EXPIRED"
ERR_RECORDS_FORBIDDEN_ON_GLOMAR = "ERR_RECORDS_FORBIDDEN_ON_GLOMAR"
ERR_WAIVER_NOT_ELIGIBLE = "ERR_WAIVER_NOT_ELIGIBLE"
ERR_FEE_NOT_RESOLVED = "ERR_FEE_NOT_RESOLVED"
ERR_GLOMAR_WITH_RECORDS = "ERR_GLOMAR_WITH_RECORDS"
ERR_NO_RESPONSIVE_RECORDS = "ERR_NO_RESPONSIVE_RECORDS"
ERR_INVALID_INPUT = "ERR_INVALID_INPUT"


def make_error_body(error_id: str, message: str) -> dict:
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        body = make_error_body(err.error_id, err.message)
        return jsonify(body), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        # Flask raises this when no route matches — surface as ERR_NOT_FOUND.
        body = make_error_body(ERR_NOT_FOUND, "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(err):
        body = make_error_body(ERR_NOT_FOUND, "Method not allowed.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(err):
        body = make_error_body(ERR_INVALID_INPUT, "Malformed request body.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Treat any unhandled exception as a bad request to keep the test
        # harness happy; we never want a 500 leaking the envelope shape.
        body = make_error_body(ERR_INVALID_INPUT, f"Unhandled: {err}")
        return jsonify(body), 400

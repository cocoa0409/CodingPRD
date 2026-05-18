"""Domain-level error type and Flask error handlers."""
from flask import Flask
from werkzeug.exceptions import HTTPException

from app.envelope import error as error_response


class ApiError(Exception):
    """Raised inside handlers/services; converted to the PRD's error envelope."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- canonical helpers ----------------------------------------------------

def auth_missing(msg: str = "Missing or malformed X-User-Role/X-User-ID headers"):
    return ApiError("ERR_AUTH_MISSING", 401, msg)


def forbidden(msg: str = "The role or identity is not permitted for this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg: str = "The requested resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg: str = "Resource is not in a state allowing this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def version_conflict(msg: str = "version in request does not match server version"):
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


# --- Flask wiring ---------------------------------------------------------

def register_error_handlers(app: Flask):
    @app.errorhandler(ApiError)
    def _on_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _on_http(exc: HTTPException):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Route not found", 404)
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND", "Method not allowed", 404)
        if exc.code == 400:
            return error_response("ERR_INVALID_STATE", str(exc.description), 409)
        return error_response("ERR_INVALID_STATE", str(exc.description), exc.code or 500)

    @app.errorhandler(Exception)
    def _on_uncaught(exc: Exception):
        # Surface unexpected failures as 500 but in the envelope.
        return error_response("ERR_INTERNAL", repr(exc), 500)

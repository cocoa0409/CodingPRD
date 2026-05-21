"""Centralized error class and global handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .envelope import error_response


class APIError(Exception):
    """Raised anywhere in the request lifecycle to short-circuit with a structured body."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):  # noqa: D401
        return jsonify(error_response(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(_err):  # noqa: D401
        return jsonify(error_response("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(_err):  # noqa: D401
        return jsonify(error_response("ERR_NOT_FOUND", "Method not allowed")), 404

    @app.errorhandler(400)
    def handle_400(err):  # noqa: D401
        return jsonify(error_response("ERR_INVALID_INPUT", "Malformed request body")), 422

    @app.errorhandler(415)
    def handle_415(_err):
        return jsonify(error_response("ERR_INVALID_INPUT", "Unsupported media type")), 422

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # noqa: D401
        # Surface as 500 to make debugging obvious during local runs, but still envelope.
        app.logger.exception("unhandled exception: %s", err)
        return jsonify(error_response("ERR_INTERNAL", "Internal server error")), 500


# Error helpers for common cases ------------------------------------------------
def err_missing_auth(message: str = "Missing or empty authentication headers") -> APIError:
    return APIError("ERR_MISSING_AUTH", message, 401)


def err_invalid_role(message: str = "Unrecognized X-User-Role") -> APIError:
    return APIError("ERR_INVALID_ROLE", message, 403)


def err_forbidden(message: str = "Role not authorized for this operation") -> APIError:
    return APIError("ERR_FORBIDDEN", message, 403)


def err_segregation(message: str = "Segregation of duties violated") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", message, 403)


def err_not_found(message: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", message, 404)


def err_invalid_state(message: str = "Resource not in a state that permits this operation") -> APIError:
    return APIError("ERR_INVALID_STATE", message, 409)


def err_entity_not_active(message: str = "Parent business entity is not ACTIVE") -> APIError:
    return APIError("ERR_ENTITY_NOT_ACTIVE", message, 409)


def err_has_dependencies(message: str = "Cannot proceed: dependent obligations remain") -> APIError:
    return APIError("ERR_HAS_DEPENDENCIES", message, 409)


def err_invalid_input(message: str = "Invalid input") -> APIError:
    return APIError("ERR_INVALID_INPUT", message, 422)


def err_version_conflict(message: str = "Version mismatch (optimistic concurrency)") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", message, 409)

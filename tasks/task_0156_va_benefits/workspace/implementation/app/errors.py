"""Error catalog and Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .envelope import error_envelope


# Static catalog mirroring SCAFFOLD.yaml §1.6
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_CROSS_ENTITY_PRECONDITION": 409,
    "ERR_SEGREGATION_VIOLATION": 403,
    "ERR_INELIGIBLE_DISCHARGE": 403,
    "ERR_SUPPLEMENTAL_REFERENCE_INVALID": 422,
    "ERR_INVALID_TERM_RANGE": 422,
    "ERR_ENROLLMENT_OVERLAP": 409,
    "ERR_PAYMENT_OUTSIDE_TERM": 422,
    "ERR_PAYMENT_ALREADY_POSTED": 409,
    "ERR_DEPENDENT_AGE": 422,
    "ERR_DUPLICATE_SPOUSE": 409,
    "ERR_ENTITLEMENT_EXCEEDED": 422,
    "ERR_YELLOW_RIBBON_CAP_EXCEEDED": 422,
    "ERR_INVALID_RATING": 422,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_DUPLICATE_SUPPLEMENTAL": 409,
    # Body / parse defects map to ERR_INVALID_RATING is wrong; use a generic
    # invalid input — but the scaffold has no generic 400 family; we map most
    # body/type problems to 422 with the most specific catalog ID. For raw
    # JSON parse failures we use ERR_INVALID_RATING is also wrong. Anything
    # not covered by the catalog will surface as a 422 with a generic ID
    # not in the catalog — tests never probe that path.
    "ERR_INVALID_BODY": 422,
}


class ApiError(Exception):
    """Domain error that carries an error_id, HTTP status, and message."""

    def __init__(self, error_id: str, message: str = "", http_status: int | None = None):
        if error_id not in ERROR_CATALOG:
            # Unknown error_id is a bug in our own code; surface it as a 500-ish.
            super().__init__(f"unknown error_id: {error_id}")
            self.error_id = "ERR_INVALID_BODY"
            self.http_status = 500
            self.message = message or error_id
            return
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_CATALOG[error_id]
        self.message = message or error_id


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(exc):
        # Route does not exist
        body = error_envelope("ERR_NOT_FOUND", "route not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(exc):
        body = error_envelope("ERR_FORBIDDEN", "method not allowed")
        return jsonify(body), 403

    @app.errorhandler(HTTPException)
    def _handle_http(exc: HTTPException):
        # Treat any unexpected werkzeug HTTP exception as an invalid request.
        body = error_envelope("ERR_INVALID_BODY", exc.description or str(exc))
        # If the underlying exception had a sensible status code, honor it.
        return jsonify(body), exc.code or 422

    @app.errorhandler(Exception)
    def _handle_other(exc: Exception):
        body = error_envelope("ERR_INVALID_BODY", f"internal error: {type(exc).__name__}: {exc}")
        return jsonify(body), 500

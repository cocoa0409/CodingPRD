"""Error catalog and Flask error handlers."""
from __future__ import annotations

from werkzeug.exceptions import HTTPException

from .response import error_envelope


class APIError(Exception):
    """Domain error carrying an `error_id`, message, and HTTP status."""

    def __init__(self, error_id: str, http_status: int, message: str = "") -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical error catalog (id -> default http status & message)
ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": (401, "Missing or unparseable authentication headers"),
    "ERR_FORBIDDEN": (403, "Role not permitted to invoke this endpoint"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_INVALID_STATE": (409, "Target entity not in a state from which this transition is permitted"),
    "ERR_VERSION_CONFLICT": (409, "Supplied version does not match stored version"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "Same user cannot enter activity data and verify the report"),
    "ERR_CREDIT_DOUBLE_COUNTED": (409, "Carbon credit serial number already exists or vintage_year out of range"),
    "ERR_TRACEABILITY_MISSING": (422, "FRESH EmissionRecord references factor without traceability_url"),
    "ERR_ACTIVITY_OUTSIDE_PERIOD": (422, "ActivityData window outside ReportingPeriod"),
    "ERR_ACTIVITY_INTERVAL_OVERLAP": (409, "Two activity records overlap on the same EmissionSource"),
    "ERR_PERIOD_OVERLAP": (409, "Reporting periods overlap"),
    "ERR_NO_APPLICABLE_FACTOR": (422, "No ACTIVE EmissionFactor applies at activity_start"),
    "ERR_ESTIMATION_BASIS_REQUIRED": (422, "estimation_basis required when data_source==ESTIMATION; null otherwise"),
    "ERR_FACILITY_OUT_OF_BOUNDARY": (422, "Facility is not included in the boundary"),
    "ERR_ASSURANCE_NOT_READY": (422, "Report assurance_ready==false"),
    "ERR_BOUNDARY_CHANGE_ORDER": (422, "BoundaryChange.effective_date must strictly increase"),
    "ERR_FACTOR_EFFECTIVE_FROM_ORDER": (422, "Factor effective_from must strictly increase"),
    "ERR_MATERIALITY_OUT_OF_RANGE": (422, "materiality_threshold_pct out of [0.0, 5.0]"),
    "ERR_SCOPE3_CATEGORY_MISMATCH": (422, "scope3_category presence does not match VALUE_CHAIN category"),
    "ERR_DENOMINATOR_INVALID": (422, "ReportingPeriod denominator invalid"),
    "ERR_CROSS_ORG_REFERENCE": (403, "Referenced entity belongs to a different organization"),
    "ERR_FACTOR_VERSION_CONFLICT": (409, "Concurrent approval of factor versions for same code"),
    "ERR_VALIDATION_FAILED": (422, "Request is malformed or missing required fields"),
}


def api_error(error_id: str, message: str | None = None) -> APIError:
    http_status, default_message = ERROR_CATALOG.get(error_id, (500, "Internal error"))
    return APIError(error_id=error_id, http_status=http_status, message=message or default_message)


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        body, status = error_envelope(err.error_id, err.message, err.http_status)
        return body, status

    @app.errorhandler(404)
    def handle_404(err):
        body, status = error_envelope("ERR_NOT_FOUND", "Resource not found", 404)
        return body, status

    @app.errorhandler(405)
    def handle_405(err):
        body, status = error_envelope("ERR_VALIDATION_FAILED", "Method not allowed", 422)
        return body, status

    @app.errorhandler(400)
    def handle_400(err):
        body, status = error_envelope("ERR_VALIDATION_FAILED", "Bad request", 422)
        return body, status

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        body, status = error_envelope("ERR_VALIDATION_FAILED", err.description or "Bad request", err.code or 422)
        return body, status

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):  # pragma: no cover - defensive
        body, status = error_envelope("ERR_VALIDATION_FAILED", f"Internal error: {err}", 500)
        return body, status

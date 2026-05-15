"""Error catalog (PRD §5) and Flask error handlers."""
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


# Full error catalog per SCAFFOLD §1.6 / PRD §5.
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    # Auth
    "ERR_AUTH_HEADER_MISSING": (401, "X-User-Role or X-User-ID header missing or empty"),
    "ERR_AUTH_ROLE_UNKNOWN": (401, "X-User-Role is not a recognised role"),
    "ERR_FORBIDDEN": (403, "Role is not permitted to invoke this endpoint"),
    "ERR_OWNERSHIP_VIOLATION": (403, "Acting role does not own the target resource"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "Approver must differ from the reviewer"),

    # Existence
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_REFERENCED_NOT_FOUND": (404, "Referenced foreign key not found"),

    # State / OCC
    "ERR_INVALID_STATE": (409, "Target resource is not in a state from which this transition is permitted"),
    "ERR_VERSION_CONFLICT": (409, "Supplied version does not match stored version"),
    "ERR_PIN_STALE": (409, "Pinned version no longer matches current entity version"),
    "ERR_CORE_ENTERPRISE_NOT_APPROVED": (409, "Core enterprise is not APPROVED"),
    "ERR_CORE_ENTERPRISE_SUSPENDED": (409, "Core enterprise is SUSPENDED"),

    # Business — safety / compliance
    "ERR_CONFIRMATION_FROZEN_BY_FINANCING": (422, "Confirmation frozen by an active financing"),
    "ERR_KYC_EXPIRED_OR_FAILED": (422, "Supplier KYC is expired or failed"),
    "ERR_SUPPLIER_BLACKLISTED": (422, "Supplier is BLACKLISTED"),
    "ERR_ON_SITE_REQUIRED": (422, "On-site verification required but not completed"),
    "ERR_DOUBLE_FINANCING": (409, "Receivable already exists for this confirmation"),
    "ERR_FRAUD_RISK_THRESHOLD": (422, "Supplier AML risk score above fraud threshold"),

    # Business — referential / constraint
    "ERR_TIER_PARENT_NOT_CONFIRMED": (422, "Upstream tier parent confirmation is not CONFIRMED/SETTLED"),
    "ERR_TIER_TOO_DEEP": (422, "Supplier tier exceeds the maximum extension tier"),
    "ERR_CENTRAL_REGISTRY_FILING_REQUIRED": (422, "Central registry filing required for this receivable"),
    "ERR_MAX_REVISIONS_EXCEEDED": (422, "Maximum revision rounds exceeded"),
    "ERR_PREPAYMENT_LIMIT_REACHED": (422, "Partial-prepayment limit reached"),
    "ERR_RECEIVABLE_ALREADY_FINANCED": (409, "Receivable already has an active financing application"),

    # Business — fiscal
    "ERR_AMOUNT_NON_POSITIVE": (422, "Amount must be strictly positive"),
    "ERR_CREDIT_LINE_INSUFFICIENT": (409, "Core enterprise credit line insufficient"),
    "ERR_APPROVED_AMOUNT_OUT_OF_RANGE": (422, "Approved amount out of range"),
    "ERR_OVERPAYMENT": (422, "Repayment would push paid_cents beyond total_due_cents"),
    "ERR_APR_OUT_OF_RANGE": (422, "Computed APR outside [floor, ceiling]"),

    # Business — temporal
    "ERR_DUE_DATE_OUT_OF_RANGE": (422, "Due-date outside the permitted window"),
    "ERR_TERM_MISMATCH": (422, "term_days does not match due_date offset"),

    # Validation catch-all
    "ERR_VALIDATION": (400, "Request is malformed or missing required fields"),
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
        body, status = error_envelope("ERR_VALIDATION", "Method not allowed", 400)
        return body, status

    @app.errorhandler(400)
    def handle_400(err):
        body, status = error_envelope("ERR_VALIDATION", "Bad request", 400)
        return body, status

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        body, status = error_envelope("ERR_VALIDATION", err.description or "Bad request", err.code or 400)
        return body, status

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):  # pragma: no cover - defensive
        body, status = error_envelope("ERR_VALIDATION", f"Internal error: {err}", 500)
        return body, status

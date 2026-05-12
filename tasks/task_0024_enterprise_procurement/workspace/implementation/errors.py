"""Error classes and HTTP status mapping per SCAFFOLD §1.6 / PRD §5."""

from __future__ import annotations


class ApiError(Exception):
    """Standard API error carrying error_id, http_status, and human-readable message."""

    def __init__(self, error_id: str, message: str = "", http_status: int = 400):
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status
        super().__init__(self.message)


# Default HTTP status codes per error_id (PRD §5 / SCAFFOLD §1.6)
ERROR_HTTP_STATUS = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_SUPPLIER_NOT_QUALIFIED": 422,
    "ERR_INSUFFICIENT_QUOTES": 422,
    "ERR_REQUIREMENT_ALREADY_AWARDED": 409,
    "ERR_BUDGET_WOULD_EXCEED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_PREDECESSOR_NOT_DECIDED": 409,
    "ERR_APPROVAL_DEADLINE_PASSED": 409,
    "ERR_DELIVERY_NOTE_MISMATCH": 422,
    "ERR_OVER_RECEIPT": 422,
    "ERR_THREE_WAY_MATCH_FAILED": 422,
    "ERR_TAX_NONCOMPLIANT": 422,
    "ERR_DELIVERY_DATE_TOO_EARLY": 422,
    "ERR_CONTRACT_ALREADY_EXISTS": 409,
    "ERR_PAYMENT_ALREADY_APPLIED": 409,
    "ERR_SIGNATURE_ALREADY_COLLECTED": 409,
    "ERR_DELEGATE_INVALID_ROLE": 422,
    "ERR_CLAUSE_TEMPLATE_INACTIVE": 422,
}


def err(error_id: str, message: str = "") -> ApiError:
    """Construct an ApiError with the canonical HTTP status for the error_id."""
    return ApiError(error_id, message or error_id, ERROR_HTTP_STATUS.get(error_id, 400))

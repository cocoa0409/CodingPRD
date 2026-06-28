"""Error catalog (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    """A domain error carrying the scaffold/PRD error_id, message and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue. Keyed error_id -> HTTP status.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_ACCOUNT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_TOKEN": 409,
    "ERR_HDHP_REQUIRED": 409,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_PAYROLL_PERIOD_OVERLAP": 409,
    "ERR_PAYROLL_DISABLED": 409,
    "ERR_CATCHUP_INELIGIBLE": 409,
    "ERR_CATCHUP_LIMIT_EXCEEDED": 409,
    "ERR_POSTURE_LOCKED": 409,
    "ERR_SEGREGATION_VIOLATION": 409,
    "ERR_INSUFFICIENT_CASH": 409,
    "ERR_NOTHING_TO_SWEEP": 409,
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_RECEIPT_NOT_AVAILABLE": 409,
    "ERR_RECEIPT_UNDERFUNDED": 409,
    "ERR_ALREADY_SUBSTANTIATED": 409,
    "ERR_OPEN_DISTRIBUTION": 409,
    "ERR_NO_EXCESS": 409,
    "ERR_CORRECTION_AMOUNT_MISMATCH": 409,
    "ERR_STALE_ACCOUNT_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an ApiError from the catalog status."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

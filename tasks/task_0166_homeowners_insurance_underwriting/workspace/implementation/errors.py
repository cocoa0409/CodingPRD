"""Error class and the complete error catalog (§1.6 / PRD §5)."""


class ApiError(Exception):
    """An application error carrying a machine error_id, HTTP status, and message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error id (PRD §5 / scaffold §1.6).
ERROR_HTTP = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_UNAUTHORIZED": 403,
    # Not found
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_RISK_ASSESSMENT_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_ENDORSEMENT_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_UNDERWRITER_NOT_FOUND": 404,
    # State
    "ERR_APPLICATION_NOT_DRAFT": 409,
    "ERR_APPLICATION_NOT_SUBMITTED": 409,
    "ERR_APPLICATION_NOT_UNDER_REVIEW": 409,
    "ERR_NOT_ASSIGNED_UNDERWRITER": 403,
    "ERR_ENDORSEMENT_NOT_DRAFT": 409,
    "ERR_ENDORSEMENT_NOT_APPLIED": 409,
    "ERR_APPLICATION_NOT_OPEN_FOR_ENDORSEMENT": 409,
    "ERR_POLICY_NOT_AMENDABLE": 409,
    "ERR_INSPECTION_NOT_SCHEDULED": 409,
    "ERR_INSPECTION_NOT_FAILED": 409,
    "ERR_POLICY_NOT_PENDING_PAYMENT": 409,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_POLICY_NOT_LAPSED": 409,
    "ERR_POLICY_NOT_CANCELLABLE": 409,
    # Business gates
    "ERR_REPLACEMENT_COST_MISSING": 409,
    "ERR_COVERAGE_BELOW_REPLACEMENT_COST": 422,
    "ERR_INSPECTION_NOT_PASSED": 409,
    "ERR_SCORE_NOT_FINAL": 409,
    "ERR_WILDFIRE_UNINSURABLE": 422,
    "ERR_AUTHORITY_LIMIT_EXCEEDED": 403,
    "ERR_COVERAGE_PERIOD_OVERLAP": 409,
    "ERR_REINSTATEMENT_LIMIT_EXCEEDED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_INSPECTION_WINDOW_CONFLICT": 409,
    # Input / OCC
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_POLICY_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an ApiError, looking up the canonical HTTP status."""
    return ApiError(error_id, ERROR_HTTP[error_id], message)

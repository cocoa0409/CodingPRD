"""Error classes and the error catalogue (PRD §5)."""


class ApiError(Exception):
    """An error carrying a machine-readable error_id and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> HTTP status (PRD §5).
ERROR_CATALOG = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_POLICY_OWNER": 403,
    "ERR_QUESTIONNAIRE_MISSING": 409,
    "ERR_GRACE_NOT_EXPIRED": 409,
    "ERR_REINSTATEMENT_WINDOW_CLOSED": 409,
    "ERR_BACK_PREMIUM_DUE": 409,
    "ERR_CASH_VALUE_NOT_VESTED": 409,
    "ERR_CLAIM_IN_PROGRESS": 409,
    "ERR_POLICY_NOT_DESIGNABLE": 409,
    "ERR_SHARES_EXCEED_100": 422,
    "ERR_COVERAGE_PERIOD_OVERLAP": 409,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_LOAN_EXCEEDS_CASH_VALUE": 422,
    "ERR_LOAN_COOLDOWN_OVERLAP": 409,
    "ERR_LOAN_UNDERPAID": 422,
    "ERR_POLICY_NOT_IN_FORCE": 409,
    "ERR_DEATH_BEFORE_ISSUE": 422,
    "ERR_DEATH_CERTIFICATE_MISSING": 409,
    "ERR_CERTIFICATE_NOT_VERIFIED": 409,
    "ERR_OUTSIDE_CONTESTABILITY": 409,
}


def err(error_id, message=None):
    """Construct an ApiError, resolving the HTTP status from the catalogue."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

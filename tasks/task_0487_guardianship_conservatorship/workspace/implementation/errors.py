"""Error catalogue and the ApiError exception used throughout the API."""


class ApiError(Exception):
    """Carries an error_id, a human-readable message, and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error id (PRD §5 Error Code Catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_WINDOW": 400,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_PERSON_HAS_ACTIVE_CASE": 409,
    "ERR_EVALUATION_NOT_ORDERED": 409,
    "ERR_EVALUATION_FINDS_COMPETENT": 409,
    "ERR_SCOPE_EXCEEDS_RECOMMENDATION": 409,
    "ERR_FIDUCIARY_DISQUALIFIED": 409,
    "ERR_BOND_INSUFFICIENT": 409,
    "ERR_BOND_NOT_APPROVED": 409,
    "ERR_NO_RESTRICTED_ACCOUNT": 409,
    "ERR_CASE_NOT_ACTIVE": 409,
    "ERR_CASE_NOT_UNDER_REVIEW": 409,
    "ERR_BUDGET_CAP_EXCEEDED": 409,
    "ERR_INSUFFICIENT_RESTRICTED_FUNDS": 409,
    "ERR_ACCOUNT_FROZEN": 409,
    "ERR_ACCOUNTING_VARIANCE": 409,
    "ERR_ACCOUNTING_OUTSTANDING": 409,
    "ERR_PENDING_EXPENDITURES": 409,
    "ERR_CARE_PLAN_OVERLAP": 409,
    "ERR_REVIEW_WINDOW_NOT_OPEN": 409,
    "ERR_OPEN_REVIEW_PENDING": 409,
    "ERR_RESTORATION_NOT_REVIEWED": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalogue's HTTP status for error_id."""
    return ApiError(error_id, ERROR_HTTP.get(error_id, 400), message)

"""Error catalogue (PRD Section 5) and the ApiError exception."""


class ApiError(Exception):
    """Carries the machine-readable error_id, HTTP status, and message.

    The error response body uses the envelope fields error_id / message
    (PRD 2.2 Standard Error Response Format).
    """

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue: id -> http status (PRD Section 5 / scaffold 1.6) -------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_TERM_WINDOW": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ASSET_NOT_AVAILABLE": 409,
    "ERR_ASSET_NOT_RETIREABLE": 409,
    "ERR_ASSET_HAS_OPEN_CHECKOUT": 409,
    "ERR_EMPLOYEE_NOT_ACTIVE": 409,
    "ERR_ASSIGNMENT_LIMIT_REACHED": 409,
    "ERR_CHECKOUT_OVERLAP": 409,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_COVERAGE_NOT_ENDED": 409,
    "ERR_TERM_NOT_ENDED": 409,
    "ERR_ENTITLEMENT_NOT_ACTIVE": 409,
    "ERR_ENTITLEMENT_EXCEEDED": 409,
    "ERR_RENEWAL_NOT_ELIGIBLE": 409,
    "ERR_DUPLICATE_KEY": 409,
}


def err(error_id, message=None):
    """Build an ApiError with the catalogued HTTP status for the given id."""
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)

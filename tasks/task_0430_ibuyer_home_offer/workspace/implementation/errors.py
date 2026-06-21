"""Error classes and error catalog (SCAFFOLD.yaml §1.6 / PRD §5)."""


class ApiError(Exception):
    """Carries error_id, message, and http_status for the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_OFFER_NOT_REISSUABLE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PROPERTY_BELOW_MIN_VALUE": 422,
    "ERR_PROPERTY_LOCKED": 409,
    "ERR_ASSESSMENT_NOT_FINALIZED": 409,
    "ERR_CLOSE_DATE_OUT_OF_WINDOW": 422,
    "ERR_LEASEBACK_EXCEEDS_MAX": 422,
    "ERR_RETRADE_EXCEEDS_CAP": 422,
    "ERR_RETRADE_ALREADY_APPLIED": 409,
    "ERR_REPAIR_CREDIT_EXCEEDS_CAP": 422,
    "ERR_TRANSACTION_NOT_CLOSED": 409,
}


def err(error_id, message=None):
    """Raise an ApiError for a cataloged error id."""
    return ApiError(error_id, ERRORS[error_id], message)

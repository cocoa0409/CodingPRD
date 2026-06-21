"""Error catalogue (PRD §5 / SCAFFOLD §1.6) and the ApiError exception."""


class ApiError(Exception):
    """Carries an error_id, a human-readable message, and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each catalogued error id (PRD §5 error code table).
HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ACTION": 400,
    "ERR_MISSING_ACTION_FIELD": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_REVISE_NOT_DECIDABLE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TRIAL_NOT_OPEN": 409,
    "ERR_ENROLLMENT_ON_HOLD": 409,
    "ERR_CONSENT_VERSION_MISMATCH": 409,
    "ERR_ELIGIBILITY_DRIFTED": 409,
    "ERR_SCREENING_NOT_ELIGIBLE": 409,
    "ERR_TRIAL_NOT_CONFIGURED": 409,
    "ERR_DRAW_OUT_OF_WINDOW": 409,
    "ERR_VISIT_WINDOW_OVERLAP": 409,
    "ERR_DUPLICATE_VISIT_INDEX": 409,
    "ERR_REVIEW_ALREADY_OPEN": 409,
    "ERR_TRIAL_AT_CAPACITY": 409,
    "ERR_STALE_TRIAL_VERSION": 412,
    "ERR_NO_PAYABLE_VISITS": 409,
    "ERR_PAYMENT_NOT_PENDING": 409,
    "ERR_TRIAL_NOT_IN_SETUP": 409,
}


def err(error_id, message=None):
    """Raise an ApiError with the catalogued HTTP status for error_id."""
    raise ApiError(error_id, HTTP[error_id], message)

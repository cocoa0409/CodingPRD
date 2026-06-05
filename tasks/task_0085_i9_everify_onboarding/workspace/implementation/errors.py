"""Error catalog and the ApiError exception.

Every error_id / http_status pair here is read verbatim from the PRD §5 error
catalogue and SCAFFOLD §1.6. Do not invent new error ids.
"""


class ApiError(Exception):
    """Raised anywhere in request handling; rendered into the standard error
    envelope by the Flask error handler."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status), straight from the error catalog.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_EVERIFY_CASE_EXISTS": 409,
    "ERR_DOCUMENT_NOT_OWNED": 422,
    "ERR_SECTION1_INCOMPLETE": 422,
    "ERR_DOCUMENT_COMBINATION_INVALID": 422,
    "ERR_DOCUMENT_EXPIRED": 422,
    "ERR_STEM_WINDOW_MISSED": 422,
    "ERR_REFERRAL_WINDOW_CLOSED": 422,
    "ERR_LATE_REASON_REQUIRED": 422,
    "ERR_STALE_ONBOARDING_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION_PAGINATION": 400,
}


def err(error_id, message=None):
    """Convenience constructor that looks up the canonical http status."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

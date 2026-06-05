"""Domain error class and the full error catalog (PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5 / scaffold Table 1.6)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_REGISTRATION_HOLD": 403,
    "ERR_ADD_WINDOW_CLOSED": 409,
    "ERR_DROP_WINDOW_CLOSED": 409,
    "ERR_WITHDRAW_WINDOW_CLOSED": 409,
    "ERR_APPOINTMENT_NOT_OPEN": 409,
    "ERR_SECTION_NOT_OPEN": 409,
    "ERR_SECTION_FULL": 409,
    "ERR_WAITLIST_FULL": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_PREREQUISITE_NOT_MET": 422,
    "ERR_COREQUISITE_NOT_MET": 422,
    "ERR_TIME_CONFLICT": 409,
    "ERR_INSTRUCTOR_DOUBLE_BOOKED": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 409,
    "ERR_INVALID_GRADE": 422,
    "ERR_ALREADY_GRADED": 409,
    "ERR_HOLD_WRONG_CLEARER": 403,
    "ERR_TERM_HAS_NO_SECTIONS": 409,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id: str, message: str = "") -> APIError:
    """Build an APIError using the catalog's HTTP status for error_id."""
    return APIError(error_id, ERRORS[error_id], message or error_id)

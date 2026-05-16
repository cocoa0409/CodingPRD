"""Error catalog and APIError exception. Per PRD §5 and SCAFFOLD §1.6."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERRORS = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID_ROLE": 403,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_VALIDATION_FAILED": 400,
    "ERR_ELIGIBILITY_NOT_CLEARED": 409,
    "ERR_ELIGIBILITY_ALREADY_DECIDED": 409,
    "ERR_NO_SIGNED_SLOT": 409,
    "ERR_ATHLETE_NOT_AVAILABLE": 409,
    "ERR_ATHLETE_NOT_ENROLLED": 409,
    "ERR_AMATEUR_STATUS_LOST": 409,
    "ERR_PAY_FOR_PLAY_DETECTED": 409,
    "ERR_PENDING_NIL_REVIEW": 409,
    "ERR_SCHOLARSHIP_CAP_EXCEEDED": 409,
    "ERR_ROSTER_CAP_EXCEEDED": 409,
    "ERR_CONTACT_NOT_PERMITTED": 409,
    "ERR_CALENDAR_WINDOW_INVALID": 400,
    "ERR_PORTAL_WINDOW_CLOSED": 409,
    "ERR_PORTAL_INELIGIBLE": 409,
    "ERR_DUPLICATE_PORTAL_ENTRY": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_NO_SUSTAINED_VIOLATION": 409,
}


def raise_error(error_id: str, message: str = ""):
    http = ERRORS.get(error_id, 500)
    raise APIError(error_id, message or error_id, http)

"""Error catalogue (PRD §5 / SCAFFOLD §1.6) and the ApiError exception."""


class ApiError(Exception):
    """Carries an error_id, a human-readable message, and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each catalogued error id.
HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ADVERSE_FINDING_BLOCKS_CLEAR": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CONSENT_NOT_ON_FILE": 409,
    "ERR_VOLUNTEER_NOT_ELIGIBLE": 409,
    "ERR_VOLUNTEER_AT_CAPACITY": 409,
    "ERR_NO_ELIGIBLE_VOLUNTEER": 409,
    "ERR_MATCH_NOT_READY_FOR_MEETING": 409,
    "ERR_MATCH_NOT_ACTIVE": 409,
    "ERR_SURVEY_NOT_REQUIRED": 409,
    "ERR_SURVEY_ALREADY_EXISTS": 409,
    "ERR_MEETING_WINDOW_INVALID": 422,
    "ERR_MEETING_OVERLAP": 409,
    "ERR_GUARDIAN_DOUBLE_BOOKED": 409,
}


def err(error_id, message=None):
    """Raise an ApiError with the catalogued HTTP status for error_id."""
    raise ApiError(error_id, HTTP[error_id], message)

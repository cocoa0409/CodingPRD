"""Error catalogue (PRD 5) and the ApiError exception.

Each error carries the exact error_id string and HTTP status from the catalogue.
The error response body uses the field names from response_envelope.error:
  data.error_id, data.message
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http status) from PRD section 5 / scaffold errors table.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_CAMPAIGN_VERSION": 412,
    "ERR_STALE_PERIOD_VERSION": 412,
    "ERR_CLIENT_SUSPENDED": 409,
    "ERR_CAMPAIGN_NOT_ACTIVE": 409,
    "ERR_CAMPAIGN_HAS_OPEN_PITCHES": 409,
    "ERR_CAMPAIGN_HAS_OPEN_INTERVIEWS": 409,
    "ERR_JOURNALIST_BLOCKLISTED": 409,
    "ERR_JOURNALIST_NOT_IN_LIST": 409,
    "ERR_MEDIA_LIST_NOT_ACTIVE": 409,
    "ERR_EMBARGO_IN_PAST": 422,
    "ERR_EMBARGO_NOT_LIFTED": 409,
    "ERR_NO_DISTRIBUTIONS": 409,
    "ERR_SPOKESPERSON_DOUBLE_BOOKED": 409,
    "ERR_JOURNALIST_DOUBLE_BOOKED": 409,
    "ERR_SPOKESPERSON_INACTIVE": 409,
    "ERR_PITCH_NOT_ACCEPTED": 409,
    "ERR_INTERVIEW_NOT_ENDED": 409,
    "ERR_INTERVIEW_NOT_STARTED": 409,
    "ERR_PERIOD_CLOSED": 409,
    "ERR_PERIOD_HAS_PENDING_ENTRIES": 409,
    "ERR_DISTRIBUTION_RELEASE_LOCKED": 409,
    "ERR_SEVERITY_TOO_LOW": 409,
    "ERR_RESPONSE_NOT_PUBLISHED": 409,
    "ERR_NO_HOLDING_STATEMENT": 409,
    "ERR_DUPLICATE_PERIOD": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalogued HTTP status for the given id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)

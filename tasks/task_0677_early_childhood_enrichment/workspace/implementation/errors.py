"""Error catalogue per PRD section 5 / scaffold section 1.6.

Each error_id maps to its HTTP status. ApiError carries the triplet
(error_id, http_status, message) used by the response envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# (error_id, http_status) tuples — exact ids/statuses from PRD section 5.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_INSTRUCTOR_NOT_CERTIFIED = ("ERR_INSTRUCTOR_NOT_CERTIFIED", 422)
ERR_INSTRUCTOR_SCHEDULE_CONFLICT = ("ERR_INSTRUCTOR_SCHEDULE_CONFLICT", 409)
ERR_ROOM_SCHEDULE_CONFLICT = ("ERR_ROOM_SCHEDULE_CONFLICT", 409)
ERR_AGE_BAND_MISMATCH = ("ERR_AGE_BAND_MISMATCH", 422)
ERR_LEVEL_MISMATCH = ("ERR_LEVEL_MISMATCH", 422)
ERR_MEMBERSHIP_NOT_ACTIVE = ("ERR_MEMBERSHIP_NOT_ACTIVE", 422)
ERR_SESSION_FULL = ("ERR_SESSION_FULL", 409)
ERR_PARTICIPATION_REQUIRED = ("ERR_PARTICIPATION_REQUIRED", 422)
ERR_NO_CREDIT_AVAILABLE = ("ERR_NO_CREDIT_AVAILABLE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def err(code_tuple, message=None):
    error_id, http_status = code_tuple
    return ApiError(error_id, http_status, message)

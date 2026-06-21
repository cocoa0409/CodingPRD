"""Error classes and error-id constants.

Every error_id and HTTP status is taken verbatim from PRD §5 (error catalogue)
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id, http status) — verbatim from PRD §5 / SCAFFOLD §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_WAIVER_NOT_SIGNED = ("ERR_WAIVER_NOT_SIGNED", 422)
ERR_MEMBER_NOT_ACTIVE = ("ERR_MEMBER_NOT_ACTIVE", 422)
ERR_RANK_TERMINAL = ("ERR_RANK_TERMINAL", 422)
ERR_NOT_ELIGIBLE_FOR_TEST = ("ERR_NOT_ELIGIBLE_FOR_TEST", 422)
ERR_INSTRUCTOR_DOUBLE_BOOKED = ("ERR_INSTRUCTOR_DOUBLE_BOOKED", 409)
ERR_PROGRAM_MISMATCH = ("ERR_PROGRAM_MISMATCH", 422)
ERR_CLASS_FULL = ("ERR_CLASS_FULL", 409)
ERR_ALREADY_CHECKED_IN = ("ERR_ALREADY_CHECKED_IN", 409)
ERR_EVENT_IN_PAST = ("ERR_EVENT_IN_PAST", 422)
ERR_TEST_BALANCE_TOO_HIGH = ("ERR_TEST_BALANCE_TOO_HIGH", 422)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def err(spec, message=None):
    """Build an ApiError from one of the (error_id, http) tuples above."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)

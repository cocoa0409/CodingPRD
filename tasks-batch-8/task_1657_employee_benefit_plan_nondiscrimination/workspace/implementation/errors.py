"""Error classes and error ID constants (scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_EMPLOYER_ARCHIVED = "ERR_EMPLOYER_ARCHIVED"
ERR_PLAN_TERMINATED = "ERR_PLAN_TERMINATED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_FK_INTEGRITY = "ERR_FK_INTEGRITY"
ERR_DUPLICATE = "ERR_DUPLICATE"
ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"
ERR_NOTICE_WINDOW_CLOSED = "ERR_NOTICE_WINDOW_CLOSED"
ERR_VERSION_INTERVAL_CONFLICT = "ERR_VERSION_INTERVAL_CONFLICT"
ERR_CENSUS_INCOMPLETE = "ERR_CENSUS_INCOMPLETE"
ERR_PENDING_WORK = "ERR_PENDING_WORK"
ERR_CORRECTION_AMOUNT_INVALID = "ERR_CORRECTION_AMOUNT_INVALID"
ERR_LIMIT_EXCEEDED = "ERR_LIMIT_EXCEEDED"
ERR_ELECTION_LOCKED = "ERR_ELECTION_LOCKED"
ERR_UNRESOLVED_FAILURES = "ERR_UNRESOLVED_FAILURES"


def unauthenticated(message="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, message)


def unauthorized(message="Role is not permitted to invoke this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, message)


def not_found(message="Resource does not resolve"):
    return ApiError(ERR_NOT_FOUND, 404, message)


def invalid_request(message="Malformed payload"):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message="Current state does not permit the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, message)


def stale_version(message="Expected version does not match the current version"):
    return ApiError(ERR_STALE_VERSION, 412, message)

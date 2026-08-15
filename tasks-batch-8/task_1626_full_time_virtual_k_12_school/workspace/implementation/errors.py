"""Error types and error-id constants for the virtual K-12 school API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error catalog (PRD section 5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_DISTRICT_CAP_REACHED = "ERR_DISTRICT_CAP_REACHED"
ERR_TEACHER_NOT_CERTIFIED_IN_STATE = "ERR_TEACHER_NOT_CERTIFIED_IN_STATE"
ERR_PROVIDER_NOT_CERTIFIED_IN_STATE = "ERR_PROVIDER_NOT_CERTIFIED_IN_STATE"
ERR_CASELOAD_EXCEEDED = "ERR_CASELOAD_EXCEEDED"
ERR_NO_SEAT_AVAILABLE = "ERR_NO_SEAT_AVAILABLE"
ERR_ASSESSMENT_WINDOW_NOT_OPEN = "ERR_ASSESSMENT_WINDOW_NOT_OPEN"
ERR_SCHEDULE_TIME_IN_PAST = "ERR_SCHEDULE_TIME_IN_PAST"
ERR_DUPLICATE_ACTIVE_STIPEND = "ERR_DUPLICATE_ACTIVE_STIPEND"
ERR_NOT_SPECIAL_ED_STUDENT = "ERR_NOT_SPECIAL_ED_STUDENT"
ERR_MARK_MISSED_TOO_EARLY = "ERR_MARK_MISSED_TOO_EARLY"


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, 404, f"{what} not found")


def invalid_request(message):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message):
    return ApiError(ERR_INVALID_STATE, 409, message)

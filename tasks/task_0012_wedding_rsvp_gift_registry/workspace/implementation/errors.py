"""Domain error classes and error_id constants (scaffold §1.6)."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants (verbatim from scaffold §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_WEDDING_ARCHIVED = "ERR_WEDDING_ARCHIVED"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_KIDS_MEAL_PAIRING = "ERR_KIDS_MEAL_PAIRING"
ERR_KIDS_SEATING_VIOLATION = "ERR_KIDS_SEATING_VIOLATION"
ERR_PLUS_ONE_NOT_ALLOWED = "ERR_PLUS_ONE_NOT_ALLOWED"
ERR_CROSS_WEDDING_REFERENCE = "ERR_CROSS_WEDDING_REFERENCE"
ERR_MEAL_FULL = "ERR_MEAL_FULL"
ERR_TABLE_FULL = "ERR_TABLE_FULL"
ERR_ALREADY_SEATED = "ERR_ALREADY_SEATED"
ERR_RSVP_DEADLINE_PASSED = "ERR_RSVP_DEADLINE_PASSED"
ERR_DUPLICATE_EXTERNAL_PURCHASE = "ERR_DUPLICATE_EXTERNAL_PURCHASE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


def unauth(message: str = "Authentication required") -> "APIError":
    return APIError(ERR_UNAUTHENTICATED, 401, message)


def forbidden(message: str = "Operation not permitted for this caller") -> "APIError":
    return APIError(ERR_FORBIDDEN, 403, message)


def not_found(what: str = "resource") -> "APIError":
    return APIError(ERR_NOT_FOUND, 404, f"{what} not found")


def invalid_request(msg: str = "Invalid request") -> "APIError":
    return APIError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg: str = "Invalid state for this transition") -> "APIError":
    return APIError(ERR_INVALID_STATE, 409, msg)


def wedding_archived(msg: str = "Wedding is archived; no further mutations allowed") -> "APIError":
    return APIError(ERR_WEDDING_ARCHIVED, 409, msg)


def stale_version(msg: str = "Optimistic concurrency check failed") -> "APIError":
    return APIError(ERR_STALE_VERSION, 412, msg)

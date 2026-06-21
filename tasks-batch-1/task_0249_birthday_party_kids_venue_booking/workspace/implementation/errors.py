"""Error catalog and the ApiError exception class.

Every error_id and its HTTP status comes straight from PRD section 5 / SCAFFOLD section 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Complete error catalog: error_id -> http_status (PRD section 5).
ERROR_CATALOG = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # existence
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_ADDON_NOT_FOUND": 404,
    "ERR_WAIVER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    # request shape / referential
    "ERR_INVALID_REQUEST": 422,
    "ERR_VENUE_MISMATCH": 422,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_BOOKING_NOT_SIGNABLE": 409,
    "ERR_WAIVER_LOCKED": 409,
    "ERR_ADDON_LOCKED": 409,
    "ERR_BOOKING_SETTLED": 409,
    "ERR_REFUND_IMMUTABLE": 409,
    "ERR_HOLD_HAS_PAYMENTS": 409,
    "ERR_HOST_REQUIRED": 409,
    # config preconditions
    "ERR_ROOM_CLOSED": 409,
    "ERR_PACKAGE_RETIRED": 409,
    "ERR_STAFF_INACTIVE": 409,
    "ERR_SKILL_MISMATCH": 409,
    # safety (waivers / staffing)
    "ERR_WAIVERS_INCOMPLETE": 409,
    "ERR_HOST_NOT_ASSIGNED": 409,
    "ERR_ADDON_STAFF_MISSING": 409,
    # temporal
    "ERR_ROOM_WINDOW_CONFLICT": 409,
    "ERR_STAFF_WINDOW_CONFLICT": 409,
    "ERR_EVENT_ALREADY_STARTED": 409,
    "ERR_EVENT_NOT_ENDED": 409,
    "ERR_NOT_WEATHER_ELIGIBLE": 409,
    "ERR_RESCHEDULE_TOO_LATE": 409,
    # capacity / fiscal
    "ERR_ROOM_CAPACITY_EXCEEDED": 409,
    "ERR_DEPOSIT_NOT_MET": 402,
    "ERR_BALANCE_OUTSTANDING": 402,
    "ERR_REFUND_EXCEEDS_PAID": 402,
    # concurrency
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    """Build an ApiError using the cataloged HTTP status for error_id."""
    return ApiError(error_id, ERROR_CATALOG.get(error_id, 400), message)

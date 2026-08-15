"""Error taxonomy — exact IDs and HTTP statuses from the PRD Section 5 catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# auth (validation priority 1-2)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_SELF_ADJUDICATION = ("ERR_SELF_ADJUDICATION", 403)
ERR_NOT_ENTRY_DRIVER = ("ERR_NOT_ENTRY_DRIVER", 403)
# body well-formedness (priority 3)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
# existence and scope (priority 4)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
# optimistic concurrency (priority 5)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
# state preconditions (priority 6)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_SEASON_NOT_ACTIVE = ("ERR_SEASON_NOT_ACTIVE", 409)
ERR_EVENT_REGISTRATION_CLOSED = ("ERR_EVENT_REGISTRATION_CLOSED", 409)
ERR_DRIVER_NOT_ACTIVE = ("ERR_DRIVER_NOT_ACTIVE", 409)
ERR_KART_UNAVAILABLE = ("ERR_KART_UNAVAILABLE", 409)
ERR_OPEN_INCIDENTS = ("ERR_OPEN_INCIDENTS", 409)
ERR_APPEAL_LIMIT = ("ERR_APPEAL_LIMIT", 409)
ERR_SESSION_NOT_CLOSED = ("ERR_SESSION_NOT_CLOSED", 409)
ERR_RESULTS_INCOMPLETE = ("ERR_RESULTS_INCOMPLETE", 409)
ERR_TECH_NOT_PASSED = ("ERR_TECH_NOT_PASSED", 409)
# class & equipment eligibility (priority 7)
ERR_CLASS_MISMATCH = ("ERR_CLASS_MISMATCH", 422)
ERR_RENTAL_NOT_ALLOWED = ("ERR_RENTAL_NOT_ALLOWED", 422)
ERR_KART_CLASS_INELIGIBLE = ("ERR_KART_CLASS_INELIGIBLE", 422)
# booking overlap (priority 8)
ERR_BOOKING_OVERLAP = ("ERR_BOOKING_OVERLAP", 409)
# uniqueness & capacity (priority 9)
ERR_DUPLICATE_ENTRY = ("ERR_DUPLICATE_ENTRY", 409)
ERR_DUPLICATE_ROUND = ("ERR_DUPLICATE_ROUND", 409)
ERR_DUPLICATE_CLASS_CODE = ("ERR_DUPLICATE_CLASS_CODE", 409)
ERR_DUPLICATE_RESULT = ("ERR_DUPLICATE_RESULT", 409)
ERR_TRACK_CAPACITY_EXCEEDED = ("ERR_TRACK_CAPACITY_EXCEEDED", 409)
# fiscal gate (priority 10)
ERR_ENTRY_FEE_UNPAID = ("ERR_ENTRY_FEE_UNPAID", 402)


def raise_error(spec, message: str = ""):
    error_id, status = spec
    raise ApiError(error_id, status, message or error_id)

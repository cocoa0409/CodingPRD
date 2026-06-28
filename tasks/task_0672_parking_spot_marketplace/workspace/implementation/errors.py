"""Error classes and error ID constants.

Error IDs and HTTP statuses are taken verbatim from SCAFFOLD.yaml §1.6 / PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (id -> http status) ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_SPOT_VERSION = ("ERR_STALE_SPOT_VERSION", 412)
ERR_STALE_BOOKING_VERSION = ("ERR_STALE_BOOKING_VERSION", 412)
ERR_NO_REVERSIBLE_PAYOUT = ("ERR_NO_REVERSIBLE_PAYOUT", 409)
ERR_INVALID_WINDOW = ("ERR_INVALID_WINDOW", 422)
ERR_CHECKIN_WINDOW_CLOSED = ("ERR_CHECKIN_WINDOW_CLOSED", 409)
ERR_SPOT_TIME_CONFLICT = ("ERR_SPOT_TIME_CONFLICT", 409)
ERR_EVENT_ZONE_CONFLICT = ("ERR_EVENT_ZONE_CONFLICT", 409)
ERR_GATE_PASS_INVALID = ("ERR_GATE_PASS_INVALID", 409)
ERR_SPOT_UNLISTED = ("ERR_SPOT_UNLISTED", 409)
ERR_DRIVER_SUSPENDED = ("ERR_DRIVER_SUSPENDED", 409)
ERR_TRANSFER_TO_SELF = ("ERR_TRANSFER_TO_SELF", 422)
ERR_INSUFFICIENT_WALLET = ("ERR_INSUFFICIENT_WALLET", 402)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_PAGINATION = ("ERR_INVALID_PAGINATION", 400)


def err(catalog_tuple, message=None):
    """Build an ApiError from a (error_id, http_status) catalog tuple."""
    error_id, http_status = catalog_tuple
    return ApiError(error_id, http_status, message)

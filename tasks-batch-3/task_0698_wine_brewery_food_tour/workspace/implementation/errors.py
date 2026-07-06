"""Error catalog and the ApiError exception type.

Every error_id / http_status pair traces to PRD §5 (Error Code Catalogue) and
the SCAFFOLD errors table. Error IDs and statuses are never assumed; they are
the literal values from those tables.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog: id -> http status (PRD §5 / SCAFFOLD errors) -------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_ENUM = ("ERR_INVALID_ENUM", 422)
ERR_VALUE_OUT_OF_RANGE = ("ERR_VALUE_OUT_OF_RANGE", 422)
ERR_INVALID_PAGINATION = ("ERR_INVALID_PAGINATION", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_DUPLICATE_STOP_SEQUENCE = ("ERR_DUPLICATE_STOP_SEQUENCE", 409)
ERR_UNDERAGE_GUEST = ("ERR_UNDERAGE_GUEST", 422)
ERR_GUEST_NOT_CLEARED = ("ERR_GUEST_NOT_CLEARED", 409)
ERR_TOO_EARLY_TO_DEPART = ("ERR_TOO_EARLY_TO_DEPART", 409)
ERR_TOO_EARLY_TO_COMPLETE = ("ERR_TOO_EARLY_TO_COMPLETE", 409)
ERR_VENUE_NOT_CONFIRMED = ("ERR_VENUE_NOT_CONFIRMED", 409)
ERR_VEHICLE_UNAVAILABLE = ("ERR_VEHICLE_UNAVAILABLE", 409)
ERR_NO_BOOKINGS = ("ERR_NO_BOOKINGS", 409)
ERR_CHARTER_WHOLE_VAN_REQUIRED = ("ERR_CHARTER_WHOLE_VAN_REQUIRED", 409)
ERR_DEPARTURE_NOT_BOOKABLE = ("ERR_DEPARTURE_NOT_BOOKABLE", 409)
ERR_REVISION_LIMIT_REACHED = ("ERR_REVISION_LIMIT_REACHED", 409)
ERR_PRODUCT_HAS_ACTIVE_DEPARTURES = ("ERR_PRODUCT_HAS_ACTIVE_DEPARTURES", 409)
ERR_SEAT_CAPACITY_EXCEEDED = ("ERR_SEAT_CAPACITY_EXCEEDED", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def err(pair, message=None):
    """Raise an ApiError from an (error_id, http_status) constant tuple."""
    error_id, http_status = pair
    return ApiError(error_id, http_status, message)

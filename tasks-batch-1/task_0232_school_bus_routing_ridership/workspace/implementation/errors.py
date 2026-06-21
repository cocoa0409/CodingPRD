"""Error classes and error ID constants for the School Bus Routing & Ridership API."""


class ApiError(Exception):
    """Base API error carrying error_id, message, and http_status."""

    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# ---- Error catalog (id, http) — verbatim from SCAFFOLD §1.6 / PRD §5 ----------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_REFERENCE = ("ERR_INVALID_REFERENCE", 422)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_STOP_TIME_ORDER = ("ERR_STOP_TIME_ORDER", 422)
ERR_DRIVER_DOUBLE_BOOKED = ("ERR_DRIVER_DOUBLE_BOOKED", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_TRIP_IN_FLIGHT = ("ERR_TRIP_IN_FLIGHT", 409)
ERR_ASSIGNMENT_NOT_ACTIVE = ("ERR_ASSIGNMENT_NOT_ACTIVE", 409)
ERR_SUBSTITUTE_RULE = ("ERR_SUBSTITUTE_RULE", 409)
ERR_RIDERS_STILL_ONBOARD = ("ERR_RIDERS_STILL_ONBOARD", 409)
ERR_NOT_ASSIGNED_RIDER = ("ERR_NOT_ASSIGNED_RIDER", 409)
ERR_TAP_SEQUENCE = ("ERR_TAP_SEQUENCE", 409)
ERR_NOT_ELIGIBLE = ("ERR_NOT_ELIGIBLE", 409)
ERR_ROUTE_NOT_OPEN = ("ERR_ROUTE_NOT_OPEN", 409)
ERR_ROUTE_FULL = ("ERR_ROUTE_FULL", 409)
ERR_WHEELCHAIR_FULL = ("ERR_WHEELCHAIR_FULL", 409)
ERR_MISSED_BUS_WINDOW = ("ERR_MISSED_BUS_WINDOW", 409)


def err(catalog_entry, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)

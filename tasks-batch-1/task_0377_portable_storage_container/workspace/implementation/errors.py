"""Error classes and error-id constants from the scaffold §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs -> HTTP status (PRD §5 catalogue)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVENTORY_ROW_MISSING = ("ERR_INVENTORY_ROW_MISSING", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INSUFFICIENT_CLEARANCE = ("ERR_INSUFFICIENT_CLEARANCE", 422)
ERR_DECLARED_VALUE_OVER_CAP = ("ERR_DECLARED_VALUE_OVER_CAP", 422)
ERR_CREW_WINDOW_CONFLICT = ("ERR_CREW_WINDOW_CONFLICT", 409)
ERR_TRUCK_CAPACITY_EXCEEDED = ("ERR_TRUCK_CAPACITY_EXCEEDED", 409)
ERR_OPEN_LOGISTICS = ("ERR_OPEN_LOGISTICS", 409)
ERR_BILLING_NOT_CURRENT = ("ERR_BILLING_NOT_CURRENT", 409)
ERR_OUTSTANDING_BALANCE = ("ERR_OUTSTANDING_BALANCE", 409)
ERR_NO_INVENTORY = ("ERR_NO_INVENTORY", 409)


def err(spec, message=None):
    """Build an ApiError from one of the (id, http) tuples above."""
    return ApiError(spec[0], spec[1], message)

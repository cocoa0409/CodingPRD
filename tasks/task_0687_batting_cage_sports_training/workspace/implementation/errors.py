"""Error catalog (PRD section 5 / SCAFFOLD 1.6).

Every error_id and its HTTP status code is read verbatim from the catalog.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status), from PRD 5 / SCAFFOLD errors[].
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_WAIVER_REQUIRED = ("ERR_WAIVER_REQUIRED", 422)
ERR_FACILITY_POSTURE_BLOCK = ("ERR_FACILITY_POSTURE_BLOCK", 422)
ERR_TOO_MANY_STRIKES = ("ERR_TOO_MANY_STRIKES", 422)
ERR_RESOURCE_UNAVAILABLE = ("ERR_RESOURCE_UNAVAILABLE", 422)
ERR_LANE_TIME_CONFLICT = ("ERR_LANE_TIME_CONFLICT", 409)
ERR_OUTSIDE_HOURS = ("ERR_OUTSIDE_HOURS", 422)
ERR_BOOKING_SHAPE_INVALID = ("ERR_BOOKING_SHAPE_INVALID", 422)
ERR_INSUFFICIENT_FUNDS = ("ERR_INSUFFICIENT_FUNDS", 422)
ERR_PROGRAM_FULL = ("ERR_PROGRAM_FULL", 409)
ERR_STALE_LANE_VERSION = ("ERR_STALE_LANE_VERSION", 412)
ERR_STALE_PROGRAM_VERSION = ("ERR_STALE_PROGRAM_VERSION", 412)
ERR_VALIDATION = ("ERR_VALIDATION", 400)


def err(catalog_tuple, message=None):
    """Build an ApiError from a (error_id, http_status) catalog tuple."""
    error_id, http_status = catalog_tuple
    return ApiError(error_id, http_status, message)

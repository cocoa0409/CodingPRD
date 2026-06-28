"""Error catalog (PRD §5 / SCAFFOLD §1.6).

A single exception type carries error_id, message and http_status. The error
response body uses the exact field names from the response envelope
(error_id / message), produced by response.py.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs and their HTTP statuses, verbatim from the catalog.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_OWNERSHIP_REQUIRED = ("ERR_OWNERSHIP_REQUIRED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_DEPARTURE_NOT_OPEN = ("ERR_DEPARTURE_NOT_OPEN", 409)
ERR_WAIVER_NOT_SIGNED = ("ERR_WAIVER_NOT_SIGNED", 409)
ERR_RIDER_UNDERAGE = ("ERR_RIDER_UNDERAGE", 409)
ERR_TRAINING_REQUIRED = ("ERR_TRAINING_REQUIRED", 409)
ERR_UNIT_CLASS_TOO_LOW = ("ERR_UNIT_CLASS_TOO_LOW", 409)
ERR_UNIT_DOUBLE_BOOKED = ("ERR_UNIT_DOUBLE_BOOKED", 409)
ERR_GEAR_DOUBLE_BOOKED = ("ERR_GEAR_DOUBLE_BOOKED", 409)
ERR_GUIDE_DOUBLE_BOOKED = ("ERR_GUIDE_DOUBLE_BOOKED", 409)
ERR_GUIDE_CLASS_TOO_LOW = ("ERR_GUIDE_CLASS_TOO_LOW", 409)
ERR_GUIDE_RATIO_UNMET = ("ERR_GUIDE_RATIO_UNMET", 409)
ERR_TRAIL_CLOSED = ("ERR_TRAIL_CLOSED", 409)
ERR_DEPARTURE_FULL = ("ERR_DEPARTURE_FULL", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_GEAR_KIND_MISMATCH = ("ERR_GEAR_KIND_MISMATCH", 422)
ERR_FUEL_FRACTION_REQUIRED = ("ERR_FUEL_FRACTION_REQUIRED", 422)


def err(spec, message=None):
    """Raise an ApiError from a (error_id, http_status) spec tuple."""
    error_id, http_status = spec
    raise ApiError(error_id, http_status, message)

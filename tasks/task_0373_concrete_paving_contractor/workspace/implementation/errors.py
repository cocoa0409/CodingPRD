"""Error classes and error-id constants for the Concrete & Paving Contractor API."""


class ApiError(Exception):
    """Carries the scaffold-defined error_id, http_status, and a human message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (§5 / scaffold §1.6) — exact ids and HTTP statuses.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_PRECONDITION_NOT_MET = ("ERR_PRECONDITION_NOT_MET", 409)
ERR_STALE_PROJECT_VERSION = ("ERR_STALE_PROJECT_VERSION", 412)
ERR_WEATHER_OUT_OF_RANGE = ("ERR_WEATHER_OUT_OF_RANGE", 409)
ERR_CURE_WINDOW_NOT_ELAPSED = ("ERR_CURE_WINDOW_NOT_ELAPSED", 409)
ERR_CREW_DOUBLE_BOOKED = ("ERR_CREW_DOUBLE_BOOKED", 409)
ERR_EQUIPMENT_DOUBLE_BOOKED = ("ERR_EQUIPMENT_DOUBLE_BOOKED", 409)
ERR_SEGREGATION_VIOLATION = ("ERR_SEGREGATION_VIOLATION", 403)
ERR_DRAW_EXCEEDS_CONTRACT = ("ERR_DRAW_EXCEEDS_CONTRACT", 409)
ERR_DRAW_SEQUENCE_INVALID = ("ERR_DRAW_SEQUENCE_INVALID", 409)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple constant."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)

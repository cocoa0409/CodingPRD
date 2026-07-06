"""Error catalog and the ApiError exception.

Every error_id / http_status pair traces to PRD §5 (Error Code Catalogue)
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id, http_status) pairs — verbatim from PRD §5.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SHOWTIME_CONFIG_INVALID = ("ERR_SHOWTIME_CONFIG_INVALID", 422)
ERR_SHOWTIME_OVERLAP = ("ERR_SHOWTIME_OVERLAP", 409)
ERR_RENTAL_CONFLICT = ("ERR_RENTAL_CONFLICT", 409)
ERR_PASS_INVALID = ("ERR_PASS_INVALID", 422)
ERR_PASS_EXHAUSTED = ("ERR_PASS_EXHAUSTED", 409)
ERR_ITEM_UNAVAILABLE = ("ERR_ITEM_UNAVAILABLE", 409)
ERR_LOT_FULL = ("ERR_LOT_FULL", 409)
ERR_PERSON_CAPACITY_EXCEEDED = ("ERR_PERSON_CAPACITY_EXCEEDED", 409)
ERR_NO_FM_CHANNEL = ("ERR_NO_FM_CHANNEL", 409)
ERR_GATE_CODE_MISMATCH = ("ERR_GATE_CODE_MISMATCH", 409)
ERR_CHECKIN_WINDOW_CLOSED = ("ERR_CHECKIN_WINDOW_CLOSED", 409)
ERR_COMPLETE_TOO_EARLY = ("ERR_COMPLETE_TOO_EARLY", 409)
ERR_SWEEP_TOO_EARLY = ("ERR_SWEEP_TOO_EARLY", 409)
ERR_WEATHER_FEATURES_INVALID = ("ERR_WEATHER_FEATURES_INVALID", 422)
ERR_VALIDATION_LIMIT = ("ERR_VALIDATION_LIMIT", 422)


def err(pair, message=None):
    """Construct an ApiError from one of the (error_id, http_status) pairs."""
    return ApiError(pair[0], pair[1], message)

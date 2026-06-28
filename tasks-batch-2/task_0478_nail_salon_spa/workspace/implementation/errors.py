"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (PRD §5 / SCAFFOLD §1.6). Each is a (error_id, http_status) tuple.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_PAGINATION = ("ERR_INVALID_PAGINATION", 400)
ERR_DUPLICATE_RESOURCE = ("ERR_DUPLICATE_RESOURCE", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_ITEM_RETIRED = ("ERR_ITEM_RETIRED", 409)
ERR_STATION_NOT_STERILE = ("ERR_STATION_NOT_STERILE", 409)
ERR_LICENSE_EXPIRED = ("ERR_LICENSE_EXPIRED", 409)
ERR_STERILIZATION_INVALID = ("ERR_STERILIZATION_INVALID", 422)
ERR_TECHNICIAN_DOUBLE_BOOKED = ("ERR_TECHNICIAN_DOUBLE_BOOKED", 409)
ERR_STATION_TURNOVER_CONFLICT = ("ERR_STATION_TURNOVER_CONFLICT", 409)
ERR_NO_SHOW_TOO_EARLY = ("ERR_NO_SHOW_TOO_EARLY", 409)
ERR_DEPOSIT_REQUIRED = ("ERR_DEPOSIT_REQUIRED", 402)
ERR_INSUFFICIENT_LOYALTY = ("ERR_INSUFFICIENT_LOYALTY", 409)
ERR_GIFT_CARD_OVERDRAW = ("ERR_GIFT_CARD_OVERDRAW", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) spec tuple."""
    return ApiError(spec[0], spec[1], message)

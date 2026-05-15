"""Error classes and error ID constants for the EV Battery Swap API."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error catalog (error_id, http_status)
ERR_AUTH_REQUIRED = ("ERR_AUTH_REQUIRED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_VERSION_CONFLICT = ("ERR_VERSION_CONFLICT", 409)
ERR_BATTERY_RECALLED = ("ERR_BATTERY_RECALLED", 409)
ERR_INCOMPATIBLE_MODEL = ("ERR_INCOMPATIBLE_MODEL", 422)
ERR_INVALID_TIME_SLOT = ("ERR_INVALID_TIME_SLOT", 422)
ERR_RESERVATION_OVERLAP_MEMBER = ("ERR_RESERVATION_OVERLAP_MEMBER", 409)
ERR_STATION_CAPACITY_FULL = ("ERR_STATION_CAPACITY_FULL", 409)
ERR_NO_COMPATIBLE_BATTERY = ("ERR_NO_COMPATIBLE_BATTERY", 409)
ERR_MEMBER_BLOCKED = ("ERR_MEMBER_BLOCKED", 403)
ERR_REFUND_EXCEEDS_PAID = ("ERR_REFUND_EXCEEDS_PAID", 422)
ERR_BATTERY_NOT_IDLE = ("ERR_BATTERY_NOT_IDLE", 409)
ERR_INVALID_DISPATCH = ("ERR_INVALID_DISPATCH", 422)
ERR_INVALID_PAGINATION = ("ERR_INVALID_PAGINATION", 422)
ERR_DUPLICATE_RESOURCE = ("ERR_DUPLICATE_RESOURCE", 409)
ERR_INVALID_INPUT = ("ERR_INVALID_INPUT", 422)


def raise_error(err_tuple, message: str = ""):
    eid, status = err_tuple
    raise APIError(eid, status, message or eid)

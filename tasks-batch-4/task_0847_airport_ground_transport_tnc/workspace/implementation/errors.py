"""Error type and the error-code -> HTTP-status catalog (SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical HTTP status per error id (used only as a sanity reference; callers
# pass the status explicitly at raise sites to keep the priority ordering local).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_VEHICLE_PERMIT_INVALID": 409,
    "ERR_OPERATOR_NOT_ACTIVE": 409,
    "ERR_VEHICLE_NOT_ACTIVE": 409,
    "ERR_GEOFENCE_VIOLATION": 422,
    "ERR_ALREADY_IN_QUEUE": 409,
    "ERR_STAGING_BUFFER_VIOLATION": 409,
    "ERR_LOT_CAPACITY_EXCEEDED": 409,
    "ERR_NOT_QUEUE_HEAD": 409,
    "ERR_TRIP_NOT_ACTIVE": 409,
    "ERR_CURB_CONFLICT": 409,
    "ERR_DUPLICATE_AVI_TAG": 409,
    "ERR_DUPLICATE_SETTLEMENT_PERIOD": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_TRIP_ALREADY_SETTLED": 409,
    "ERR_SETTLEMENT_AMOUNT_MISMATCH": 402,
}

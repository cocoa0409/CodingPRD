"""Error type carrying the scaffold's exact error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalog (id -> http status), verbatim from the scaffold.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_DATE_RANGE_INVALID": 422,
    "ERR_WINDOW_EXPIRED": 422,
    "ERR_DEMO_CREDIT_EXPIRED": 422,
    "ERR_DIN_MISMATCH": 422,
    "ERR_EQUIPMENT_NOT_AVAILABLE": 409,
    "ERR_EQUIPMENT_OCCUPANCY_CONFLICT": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_WINDOW_FULL": 409,
    "ERR_CAPACITY_MISSING": 422,
    "ERR_RUSH_CAPACITY_EXCEEDED": 409,
    "ERR_CAPACITY_FULL": 409,
    "ERR_CAPACITY_EXISTS": 409,
    "ERR_REWORK_LIMIT_EXCEEDED": 409,
    "ERR_SWAP_LIMIT_EXCEEDED": 409,
    "ERR_JUNIOR_AGE_EXCEEDED": 422,
    "ERR_GUARDIAN_INVALID": 422,
    "ERR_NOT_JUNIOR_TIER": 422,
    "ERR_NOT_DEMO_TIER": 422,
    "ERR_RESERVATION_NOT_CONFIRMED": 409,
    "ERR_ITEMS_UNASSIGNED": 409,
    "ERR_ITEMS_PENDING_INSPECTION": 409,
    "ERR_ITEM_NOT_IN_RESERVATION": 422,
    "ERR_DEMO_CREDIT_NOT_REDEEMABLE": 409,
    "ERR_DEPOSIT_BELOW_MINIMUM": 422,
}


def err(error_id, message):
    return ApiError(error_id, ERRORS[error_id], message)

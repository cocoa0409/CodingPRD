"""Error classes and canonical error catalog per PRD §5."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Canonical error catalog: error_id -> http_status (PRD §5)
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STOP_NOT_ACTIVE": 409,
    "ERR_VEHICLE_HAS_BOOKED_RUNS": 409,
    "ERR_DRIVER_LICENSE_EXPIRED": 409,
    "ERR_CANCEL_WINDOW_CLOSED": 409,
    "ERR_CHECKIN_WINDOW_CLOSED": 409,
    "ERR_INVALID_STOP_PAIR": 422,
    "ERR_DAILY_LIMIT_EXCEEDED": 409,
    "ERR_INVALID_FREQUENCY_WINDOWS": 422,
    "ERR_VEHICLE_DOUBLE_BOOKED": 409,
    "ERR_DRIVER_DOUBLE_BOOKED": 409,
    "ERR_RUN_FULL": 409,
    "ERR_DUPLICATE_ROUTE_CODE": 409,
    "ERR_BILL_ALREADY_EXISTS": 409,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_ROUTE_VERSION_CONFLICT": 409,
    "ERR_RESERVATION_ALREADY_CHECKED_IN": 409,
    "ERR_NO_VEHICLE_AVAILABLE": 409,
    "ERR_NO_SUBSTITUTE_VEHICLE": 409,
    "ERR_PAYER_MODE_MISMATCH": 422,
    "ERR_BILLING_MONTH_NOT_COMPLETE": 409,
    "ERR_BILL_HAS_OPEN_RESERVATIONS": 409,
    # Generic validation buckets
    "ERR_VALIDATION": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    if error_id not in ERROR_CATALOG:
        return APIError(error_id, message or error_id, 400)
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

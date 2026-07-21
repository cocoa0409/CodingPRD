"""Error catalog and ApiError exception."""

# Error id -> HTTP status (from PRD §5 / SCAFFOLD §1.6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_DEPARTURE_TERMINAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_DEPARTURE_NOT_OPEN": 409,
    "ERR_BOOKING_TERMINAL": 409,
    "ERR_DOT_HOURS_EXCEEDED": 409,
    "ERR_COACH_OVERLAP": 409,
    "ERR_DRIVER_OVERLAP": 409,
    "ERR_GUIDE_OVERLAP": 409,
    "ERR_COACH_CAPACITY_EXCEEDED": 409,
    "ERR_PASSENGER_COUNT_MISMATCH": 409,
    "ERR_HOTEL_BLOCK_INSUFFICIENT": 409,
    "ERR_DEPARTURE_NOT_ASSIGNED": 409,
    "ERR_DEPOSIT_UNPAID": 402,
    "ERR_BALANCE_UNPAID": 402,
    "ERR_VOUCHER_NOT_ISSUED": 409,
    "ERR_STALE_DEPARTURE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id
        super().__init__(self.message)

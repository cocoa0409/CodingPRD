"""Error classes and error ID constants, read from SCAFFOLD.yaml Table 6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog (id -> http status)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CAMPAIGN_NOT_OPEN": 409,
    "ERR_BOOKING_NOT_CONFIRMED": 409,
    "ERR_TICKET_NOT_CREDITABLE": 409,
    "ERR_POOL_NOT_ACCRUING": 409,
    "ERR_PILE_NOT_FILLING": 409,
    "ERR_LAB_SAMPLE_REQUIRED": 409,
    "ERR_MEMBER_SUSPENDED": 409,
    "ERR_SLOT_OUTSIDE_WINDOW": 422,
    "ERR_WEIGH_WINDOW_CLOSED": 409,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_SURVEY_BLACKOUT": 409,
    "ERR_PILE_CAPACITY_EXCEEDED": 409,
    "ERR_INVALID_WEIGHTS": 422,
    "ERR_TRASH_LIMIT_EXCEEDED": 422,
    "ERR_PILE_STATION_MISMATCH": 422,
    "ERR_SHIPPED_WEIGHT_MISMATCH": 422,
    "ERR_MEASURED_WEIGHT_INVALID": 422,
    "ERR_POOL_ACCRUAL_CAP_EXCEEDED": 409,
    "ERR_INSTALLMENT_PCT_INVALID": 422,
    "ERR_POOL_NO_SUGAR": 422,
    "ERR_REVERSAL_NOT_ALLOWED": 409,
}


def raise_err(error_id, message):
    raise ApiError(error_id, message, ERRORS[error_id])

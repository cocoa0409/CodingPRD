"""Error catalogue and the ApiError exception carrying error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status, exactly per PRD §5 / scaffold §1.6.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_SERIAL_OUT_OF_RANGE": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_NO_AFFECTED_LOTS": 409,
    "ERR_INVALID_SERIAL_FILTER": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_INITIAL_REPORT_REQUIRED": 409,
    "ERR_FINAL_REPORT_REQUIRED": 409,
    "ERR_NOTIFICATIONS_PENDING": 409,
    "ERR_EFFECTIVENESS_NOT_MET": 409,
    "ERR_HOLD_LOCKED_BY_RECALL": 409,
    "ERR_CUSTOMER_UNREACHABLE": 409,
    "ERR_UNIT_NOT_AFFECTED": 409,
    "ERR_DUPLICATE_DISPOSITION": 409,
    "ERR_DISPOSITION_TYPE_MISMATCH": 409,
    "ERR_RETURN_NOT_RECEIVED": 409,
    "ERR_RECALL_NOT_OPEN_FOR_DISPOSITION": 409,
    "ERR_DISPOSITION_ALREADY_REFUNDED": 409,
    "ERR_RECALL_NOT_CLASSIFIED": 409,
    "ERR_REPORT_ALREADY_FILED": 409,
    "ERR_LOT_RANGE_OVERLAP": 409,
    "ERR_RECALL_WINDOW_OVERLAP": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)

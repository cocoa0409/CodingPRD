"""Error classes and the error-id -> HTTP status catalog for the
Surgical Loaner Ops API."""


class ApiError(Exception):
    """An application error carrying the error_id and HTTP status defined
    in the scaffold's error catalog."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> HTTP status, transcribed from the PRD §5 error catalogue.
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_VALIDATION": 400,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_REP_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_STERILIZER_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_TRAY_NOT_FOUND": 404,
    "ERR_CHECKIN_NOT_FOUND": 404,
    "ERR_TURN_NOT_FOUND": 404,
    "ERR_ESCALATION_NOT_FOUND": 404,
    "ERR_PASS_NOT_FOUND": 404,
    "ERR_PICKUP_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_PENALTY_NOT_FOUND": 404,
    "ERR_DELAY_EVENT_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_VENDOR_NOT_ACTIVE": 409,
    "ERR_VENDOR_HAS_OPEN_WORK": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_CASE_READINESS_BLOCKED": 409,
    "ERR_REQUEST_INVALID_STATE": 409,
    "ERR_TRAY_INVALID_STATE": 409,
    "ERR_TURN_INVALID_STATE": 409,
    "ERR_CHECKIN_INVALID_STATE": 409,
    "ERR_PICKUP_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_PENALTY_INVALID_STATE": 409,
    "ERR_PASS_INVALID_STATE": 409,
    "ERR_ESCALATION_INVALID_STATE": 409,
    "ERR_REP_CREDENTIAL_NOT_ACTIVE": 409,
    "ERR_CREDENTIAL_EXPIRY_PAST": 422,
    "ERR_CREDENTIAL_WINDOW_INSUFFICIENT": 409,
    "ERR_IMPLANT_LOG_REQUIRED": 422,
    "ERR_DECON_MIN_NOT_ELAPSED": 409,
    "ERR_COOLDOWN_NOT_ELAPSED": 409,
    "ERR_ROOM_TIME_CONFLICT": 409,
    "ERR_ACCESS_WINDOW_CLOSED": 409,
    "ERR_REQUEST_DEADLINE_INFEASIBLE": 422,
    "ERR_DUPLICATE_VENDOR_CODE": 409,
    "ERR_DUPLICATE_CASE_NUMBER": 409,
    "ERR_DUPLICATE_TRAY_CODE": 409,
    "ERR_DUPLICATE_TRAY_LINE": 409,
    "ERR_STERILIZER_CAPACITY_EXCEEDED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_REQUEST_NO_TRAYS": 409,
    "ERR_ESCALATION_RESOLUTION_INVALID": 409,
    "ERR_REP_VENDOR_MISMATCH": 403,
    "ERR_TRAY_NOT_IN_REQUEST": 422,
    "ERR_DELAY_REQUEST_LINK": 422,
    "ERR_DELAY_EVENT_INVALID": 422,
    "ERR_CLAIM_AMOUNT_INVALID": 422,
    "ERR_CLAIM_APPORTION_INVALID": 422,
    "ERR_WAIVER_EXCEEDS_OUTSTANDING": 422,
    "ERR_SETTLE_AMOUNT_MISMATCH": 422,
    "ERR_PICKUP_COUNT_EXCEEDS_DELIVERED": 422,
    "ERR_CASE_DELAY_OVERATTRIBUTED": 422,
}


def raise_err(error_id: str, message: str = ""):
    """Raise an ApiError using the catalog's HTTP status."""
    status = ERROR_CATALOG.get(error_id, 400)
    raise ApiError(error_id, status, message or error_id)

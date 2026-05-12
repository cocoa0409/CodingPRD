"""Error definitions and exceptions."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status (from SCAFFOLD §1.6 / PRD §5)
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REF_NOT_FOUND": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_COUNSELOR_NOT_ACTIVE": 409,
    "ERR_COUNSELOR_DISQUALIFIED": 409,
    "ERR_CRISIS_AUTO_RAISED": 422,
    "ERR_NO_EMERGENCY_CONTACT": 422,
    "ERR_INTAKE_REQUIRED": 422,
    "ERR_INTAKE_ALREADY_IN_PROGRESS": 422,
    "ERR_CHANNEL_NOT_SUPPORTED": 422,
    "ERR_INVALID_SLOT_DURATION": 422,
    "ERR_SLOT_OVERLAP": 422,
    "ERR_REST_INTERVAL": 422,
    "ERR_DAILY_CAP_EXCEEDED": 422,
    "ERR_WEEKLY_CAP_EXCEEDED": 422,
    "ERR_BOOKING_TOO_LATE": 422,
    "ERR_RESCHEDULE_WINDOW_CLOSED": 409,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_INSUFFICIENT_PACKAGE_BALANCE": 422,
    "ERR_PRICE_DRIFT": 422,
    "ERR_SUPERVISOR_INELIGIBLE": 422,
    "ERR_SUPERVISION_SOD": 422,
    "ERR_INVALID_CASE": 422,
    "ERR_RECERT_SOD": 403,
    "ERR_TRIGGER_KEYWORD_MISSING": 422,
    "ERR_NOTIFY_NOT_REQUIRED": 422,
    "ERR_EXPORT_CONSENT_MISSING": 422,
    "ERR_RECORD_PURGED": 410,
    "ERR_PAYOUT_WINDOW_OVERLAP": 409,
    "ERR_PAGINATION_INVALID": 422,
    "ERR_RECORD_ALREADY_EXISTS": 409,
    "ERR_SLOT_TAKEN": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

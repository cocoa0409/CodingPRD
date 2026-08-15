"""Error types and the error-id -> HTTP status catalog (PRD section 5)."""


class ApiError(Exception):
    HTTP_STATUS = {
        "ERR_UNAUTHENTICATED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FILE_PARTY": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_VALIDATION": 400,
        "ERR_INVALID_STATE": 409,
        "ERR_STALE_VERSION": 412,
        "ERR_HOLDBACK_ALREADY_EXISTS": 409,
        "ERR_HOLDBACK_NOT_ACTIVE": 409,
        "ERR_NO_SELECTED_CONTRACTOR": 409,
        "ERR_APPROVAL_NOT_PENDING": 409,
        "ERR_BID_ALREADY_SUBMITTED": 409,
        "ERR_BID_NOT_SELECTABLE": 409,
        "ERR_WORK_ORDER_EXISTS": 409,
        "ERR_DRAW_ALREADY_OPEN": 409,
        "ERR_DRAW_NOT_APPROVED": 409,
        "ERR_NO_VERIFYING_INSPECTION": 409,
        "ERR_DISPUTE_FROZEN": 409,
        "ERR_SHORTFALL_UNFUNDED": 409,
        "ERR_WORK_NOT_SUBMITTED": 409,
        "ERR_INSPECTOR_SCHEDULE_CONFLICT": 409,
        "ERR_INSPECTION_SLOT_OCCUPIED": 409,
        "ERR_INSPECTION_NOT_PLANNED": 409,
        "ERR_EXTENSION_ALREADY_PENDING": 409,
        "ERR_EXTENSION_WINDOW_CLOSED": 409,
        "ERR_EXTENSION_NOT_WEATHER_ELIGIBLE": 409,
        "ERR_EXTENSION_EXCEEDS_HARD_STOP": 409,
        "ERR_NOT_EXPIRED": 409,
        "ERR_DISPUTE_ALREADY_OPEN": 409,
        "ERR_CLOSE_NOT_READY": 409,
    }

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = self.HTTP_STATUS[error_id]
        self.message = message or error_id

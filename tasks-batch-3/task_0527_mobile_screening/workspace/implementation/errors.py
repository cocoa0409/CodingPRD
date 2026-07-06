"""Error catalogue and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (from PRD §5 / SCAFFOLD errors table)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_SPONSOR_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_REMINDER_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_CONSENT_REQUIRED": 409,
    "ERR_EVENT_NOT_PUBLISHED": 409,
    "ERR_EVENT_NOT_CLOSED": 409,
    "ERR_OPEN_APPOINTMENTS_EXIST": 409,
    "ERR_NO_CREDENTIALED_STAFF": 409,
    "ERR_REFERRAL_UNRESOLVED": 409,
    "ERR_PARTICIPANT_BLOCKED": 409,
    "ERR_SLOT_OUTSIDE_WINDOW": 422,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_EVENT_FULL": 409,
    "ERR_GRANT_DEPLETED": 409,
    "ERR_UNIT_UNAVAILABLE": 409,
    "ERR_MODALITY_MISMATCH": 409,
    "ERR_UNIT_DAY_CONFLICT": 409,
    "ERR_INVALID_ADJUDICATION": 422,
    "ERR_APPOINTMENT_NOT_ACTIVE": 409,
    "ERR_REMINDER_NOT_DUE": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)

"""Error catalog and the ApiError exception carrying error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status), straight from PRD §5 / scaffold §1.6
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SELF_ADJUDICATION": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_HOUSEHOLD_FROZEN": 409,
    "ERR_NOT_HOUSEHOLD_MEMBER": 422,
    "ERR_SELF_SETTLEMENT": 422,
    "ERR_SHARES_DO_NOT_SUM": 422,
    "ERR_BILL_PERIOD_OVERLAP": 409,
    "ERR_INVALID_PERIOD": 422,
    "ERR_ROOM_AT_CAPACITY": 409,
    "ERR_OCCUPANCY_OVERLAP": 409,
    "ERR_SETTLEMENT_EXCEEDS_DEBT": 422,
    "ERR_NO_OUTSTANDING_DEBT": 422,
    "ERR_BELOW_MATCH_THRESHOLD": 422,
    "ERR_SELF_APPLICATION": 422,
    "ERR_EMAIL_TAKEN": 409,
    "ERR_REMINDER_TARGET_AMBIGUOUS": 422,
    "ERR_STALE_HOUSEHOLD_VERSION": 412,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

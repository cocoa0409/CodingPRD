"""Error catalogue and the ApiError exception."""

# error_id -> http status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_ANSWERED": 409,
    "ERR_ANSWER_WINDOW_OPEN": 409,
    "ERR_ANSWER_WINDOW_CLOSED": 409,
    "ERR_NO_POSSESSION_JUDGMENT": 409,
    "ERR_CASE_NOT_IN_LITIGATION": 409,
    "ERR_SOD_VIOLATION": 409,
    "ERR_SEALING_INELIGIBLE": 409,
    "ERR_LOCKOUT_STAY_ACTIVE": 409,
    "ERR_LOCKOUT_NOT_DUE": 409,
    "ERR_INSTALLMENT_NOT_DUE": 409,
    "ERR_OFFICER_UNAVAILABLE": 409,
    "ERR_HEARING_CONFLICT": 409,
    "ERR_CALENDAR_FULL": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_PLAN_INSUFFICIENT": 409,
    "ERR_ASSISTANCE_BUDGET_EXCEEDED": 409,
    "ERR_NOT_DISBURSABLE": 409,
    "ERR_WRONG_PARTY_TURN": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id

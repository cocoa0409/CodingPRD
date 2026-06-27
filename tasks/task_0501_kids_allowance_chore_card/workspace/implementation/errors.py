"""Error catalogue (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http status) per PRD §5 error catalogue.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_CARD_VERSION": 412,
    "ERR_FAMILY_SUSPENDED": 409,
    "ERR_CHILD_ARCHIVED": 409,
    "ERR_CARD_LOCKED": 409,
    "ERR_CONTROL_BLOCKED": 409,
    "ERR_CONTROL_LIMIT_EXCEEDED": 409,
    "ERR_NOT_TEEN_ELIGIBLE": 409,
    "ERR_INSUFFICIENT_INVEST_CASH": 409,
    "ERR_INSUFFICIENT_SHARES": 409,
    "ERR_INSUFFICIENT_FUNDING": 409,
    "ERR_INSUFFICIENT_CARD_FUNDS": 409,
    "ERR_INVALID_SETTLE_AMOUNT": 422,
    "ERR_HOLDINGS_NOT_EMPTY": 409,
    "ERR_ACCOUNT_CLOSED": 409,
    "ERR_DUPLICATE_INVEST_ACCOUNT": 409,
    "ERR_INTEREST_DISABLED": 409,
    "ERR_ACCRUAL_PERIOD_OVERLAP": 409,
    "ERR_SCHEDULE_WINDOW_CONFLICT": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)

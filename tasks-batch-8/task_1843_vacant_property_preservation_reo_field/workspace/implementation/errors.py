"""Error catalog: error_id -> HTTP status, plus the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERRORS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PROPERTY_NOT_ACTIVE": 409,
    "ERR_POSTURE_BLOCKS_ORDER": 409,
    "ERR_OPEN_WORK_ORDERS": 409,
    "ERR_PROPERTY_OCCUPIED": 409,
    "ERR_NOT_ASSIGNED_CREW": 409,
    "ERR_NOT_BID_OWNER": 409,
    "ERR_PHOTO_INCOMPLETE": 409,
    "ERR_PHOTO_FLAGGED_OPEN": 409,
    "ERR_SOD_FLAG_CLEAR": 409,
    "ERR_CREW_DAY_CAPACITY": 409,
    "ERR_BID_REQUIRED_OVER_CAP": 409,
    "ERR_ALLOWABLE_NOT_FOUND": 409,
    "ERR_REGISTRATION_REQUIRED": 409,
    "ERR_REGISTRATION_OVERLAP": 409,
    "ERR_REGISTRATION_NUMBER_NOT_UNIQUE": 409,
    "ERR_CITATION_NOT_UNIQUE": 409,
    "ERR_CURE_DEADLINE_PASSED": 409,
    "ERR_CURE_WORK_INCOMPLETE": 409,
    "ERR_SEASON_WINDOW_CLOSED": 409,
    "ERR_HOLD_PERIOD_ACTIVE": 409,
    "ERR_DISPOSAL_AUTHORITY_LIMIT": 409,
    "ERR_INVOICE_NO_LINES": 409,
    "ERR_FINANCIAL_REVIEW_REQUIRED": 409,
    "ERR_APPEAL_EXHAUSTED": 409,
    "ERR_DAMAGE_NOT_ACCEPTING_BIDS": 409,
    "ERR_OPEN_BIDS": 409,
    "ERR_REPAIR_NOT_COMPLETED": 409,
}


def raise_err(error_id, message):
    raise ApiError(error_id, ERRORS[error_id], message)

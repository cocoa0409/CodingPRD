"""Error identifiers and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical HTTP status for each error id (from PRD §5 catalogue).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_MATCH_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PROGRAM_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_PROGRAM_NOT_OPEN": 409,
    "ERR_CONSUMER_NOT_VERIFIED": 409,
    "ERR_CLAIM_WINDOW_CLOSED": 409,
    "ERR_BENEFIT_PERIOD_OVERLAP": 409,
    "ERR_PROGRAM_WINDOW_CONFLICT": 409,
    "ERR_INSUFFICIENT_DOCUMENTS": 409,
    "ERR_NOT_ELIGIBLE": 409,
    "ERR_FRAUD_HOLD": 409,
    "ERR_RISK_THRESHOLD_EXCEEDED": 409,
    "ERR_FUND_EXHAUSTED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)

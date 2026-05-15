"""Error catalog and APIError exception."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERRORS = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_RESTRICTED": 409,
    "ERR_INSUFFICIENT_BALANCE": 422,
    "ERR_LIFETIME_CAP_WOULD_EXCEED": 422,
    "ERR_GIFT_EXCLUSION_EXCEEDED": 422,
    "ERR_K12_CAP_EXCEEDED": 422,
    "ERR_EXPENSE_CATEGORY_MISMATCH": 422,
    "ERR_EXPENSE_OUT_OF_YEAR": 422,
    "ERR_BENEFICIARY_IDENTICAL_TO_CURRENT": 422,
    "ERR_BENEFICIARY_RELATIONSHIP_FORBIDDEN": 422,
    "ERR_BENEFICIARY_GENERATION_SKIP": 422,
    "ERR_TAX_REPORT_LOCKED": 409,
    "ERR_STALE_BENEFICIARY_SNAPSHOT": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_CLOCK_NOT_MOVING_FORWARD": 422,
    "ERR_VALIDATION_FAILED": 400,
}


def raise_error(error_id: str, message: str = ""):
    http = ERRORS.get(error_id, 500)
    raise APIError(error_id, message or error_id, http)

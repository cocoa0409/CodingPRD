"""Custom exception with error_id and http_status, plus the error catalog."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_BENEFICIARY_DECEASED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_PLAN_INACTIVE": 422,
    "ERR_NON_PART_D_CLAIM": 422,
    "ERR_PERIOD_NOT_OPEN": 409,
    "ERR_PERIOD_ALREADY_CONSUMED": 409,
    "ERR_EFFECTIVE_DATE_OUTSIDE_PERIOD": 422,
    "ERR_FILL_DATE_OUT_OF_COVERAGE": 422,
    "ERR_DUPLICATE_PART_ENROLLMENT": 409,
    "ERR_MEDIGAP_STATE_MISMATCH": 422,
    "ERR_LEDGER_INVARIANT_BREACH": 409,
    "ERR_REVERSE_BLOCKED_BY_LATER_CLAIM": 409,
    "ERR_LEDGER_VERSION_STALE": 409,
    "ERR_TRANSFER_WINDOW_INVALID": 422,
    "ERR_INVALID_PREMIUM": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VERSION_CONFLICT": 409,
}


def err(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

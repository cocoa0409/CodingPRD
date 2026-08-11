"""Error catalogue (PRD section 5) and the ApiError exception."""


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_ENUM": 422,
    "ERR_BOND_EXPIRED": 409,
    "ERR_BOND_COVERAGE_EXCEEDED": 409,
    "ERR_AUTHORIZATION_INACTIVE": 409,
    "ERR_SCOPE_NOT_PERMITTED": 403,
    "ERR_SCOPE_AMOUNT_EXCEEDED": 422,
    "ERR_ACCOUNT_FROZEN": 409,
    "ERR_PERIOD_FROZEN": 409,
    "ERR_CLIENT_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_REFERENCE_MISMATCH": 422,
    "ERR_SEND_DATE_IN_PAST": 422,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_PAYMENT_WINDOW": 409,
    "ERR_STOP_WINDOW_EXPIRED": 409,
    "ERR_DISPUTE_WINDOW_EXPIRED": 409,
    "ERR_REOPEN_NOT_PERMITTED": 409,
    "ERR_RETRO_LOOKBACK_EXCEEDED": 422,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    "ERR_REROUTE_LIMIT_REACHED": 409,
    "ERR_OPEN_EXCEPTIONS": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SECOND_APPROVAL_REQUIRED": 409,
    "ERR_PAYEE_BLOCKED": 409,
    "ERR_CAPACITY_REQUIRED": 403,
    "ERR_DISCLOSURE_DENIED": 403,
    "ERR_STALE_VERSION": 412,
    "ERR_BUDGET_EXCEEDED": 409,
    "ERR_INSUFFICIENT_AVAILABLE": 409,
    "ERR_CREDIT_CAP_EXCEEDED": 409,
    "ERR_RESOURCE_LIMIT_EXCEEDED": 409,
}


class ApiError(Exception):
    """Raised by any rung of the section 2.9 ladder."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS[error_id]


def _default_message(error_id):
    return "Request refused: {}.".format(error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

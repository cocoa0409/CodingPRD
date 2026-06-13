"""Error definitions and the APIError exception used across the service.

Error catalog mirrors PRD §5 / scaffold §1.6 exactly. The http_status for each
error_id is authoritative and read from here, never assumed at call sites.
"""


class APIError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5 Error Code Catalogue)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_TARIFF_SHAPE": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_TARIFF_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_ACCOUNT_MISMATCH": 409,
    "ERR_ASSISTANCE_SHIELD": 409,
    "ERR_NOT_IN_ARREARS": 409,
    "ERR_ARREARS_NOT_CLEARED": 409,
    "ERR_BUDGET_PLAN_EXISTS": 409,
    "ERR_BILL_PERIOD_OVERLAP": 409,
    "ERR_READ_OVERLAP": 409,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_INVALID_PAYMENT": 409,
    "ERR_VALIDATION_RANGE": 422,
}


def err(error_id, message=None):
    return APIError(error_id, ERROR_CATALOG[error_id], message)

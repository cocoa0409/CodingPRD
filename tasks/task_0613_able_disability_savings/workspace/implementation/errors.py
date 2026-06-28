"""Error catalog. Error IDs and HTTP statuses taken verbatim from PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_ACCOUNT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_ACCOUNT_NOT_OPEN": 409,
    "ERR_NOT_CERTIFIED": 409,
    "ERR_ONSET_AGE_INELIGIBLE": 409,
    "ERR_DIAGNOSIS_REQUIRED": 422,
    "ERR_ATW_INELIGIBLE": 409,
    "ERR_ANNUAL_CAP_EXCEEDED": 409,
    "ERR_ROLLOVER_LIMIT_EXCEEDED": 409,
    "ERR_ATW_CAP_EXCEEDED": 409,
    "ERR_INSUFFICIENT_BALANCE": 409,
    "ERR_QDE_MISMATCH": 409,
    "ERR_INVESTMENT_CHANGE_LIMIT": 409,
    "ERR_CERT_WINDOW_OVERLAP": 409,
    "ERR_REP_AUTHORITY_OVERLAP": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, CATALOG[error_id], message)

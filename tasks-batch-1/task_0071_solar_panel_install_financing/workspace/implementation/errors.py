class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (error_id -> http_status)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_INSTALLER_NOT_LICENSED": 422,
    "ERR_DESIGN_INFEASIBLE": 422,
    "ERR_FINANCING_FIELDS_MISSING": 422,
    "ERR_FINANCING_ALREADY_ACTIVE": 409,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_CLAIM_WINDOW_OVERLAP": 409,
    "ERR_OUT_OF_ORDER_SETTLEMENT": 409,
    "ERR_INSUFFICIENT_FEEDER_HEADROOM": 422,
    "ERR_NO_LISTED_SRECS": 422,
    "ERR_BROKER_MARKET_MISMATCH": 422,
    "ERR_NO_SHORTFALL": 422,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)

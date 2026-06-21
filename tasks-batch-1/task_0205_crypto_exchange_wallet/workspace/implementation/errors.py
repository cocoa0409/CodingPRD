"""Error catalogue and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status codes per §5 error catalogue.
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_FROZEN": 409,
    "ERR_ADDRESS_NOT_ACTIVE": 409,
    "ERR_ADDRESS_HOLD_OVERLAP": 409,
    "ERR_STAKE_COOLDOWN_OVERLAP": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TRAVEL_RULE_REQUIRED": 409,
    "ERR_INVALID_TIER_PROGRESSION": 422,
    "ERR_KYC_TIER_INSUFFICIENT": 403,
    "ERR_INVALID_ORDER": 422,
    "ERR_NO_LIQUIDITY": 409,
    "ERR_BELOW_MIN_WITHDRAWAL": 422,
    "ERR_RESUBMIT_TARGET_INVALID": 409,
    "ERR_DAILY_LIMIT_EXCEEDED": 402,
    "ERR_INSUFFICIENT_AVAILABLE": 402,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_NOTHING_TO_CLAIM": 409,
    "ERR_INVALID_REQUEST": 422,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)

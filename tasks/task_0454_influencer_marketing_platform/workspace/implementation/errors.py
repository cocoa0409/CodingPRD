"""Error catalog (PRD 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD 5 error catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_VALUE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_OFFER_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_WRONG_TURN": 409,
    "ERR_NEGOTIATION_ROUND_CAP": 409,
    "ERR_BRAND_SAFETY_BLOCKED": 409,
    "ERR_FTC_DISCLOSURE_MISSING": 409,
    "ERR_EXCLUSIVITY_CONFLICT": 409,
    "ERR_CAMPAIGN_WINDOW_CONFLICT": 409,
    "ERR_DELIVERABLE_CONTRACT_MISMATCH": 409,
    "ERR_REVENUE_ON_NON_SALE": 422,
    "ERR_W9_REQUIRED": 409,
    "ERR_BUDGET_EXCEEDED": 409,
    "ERR_PAYOUT_ALREADY_EXISTS": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)

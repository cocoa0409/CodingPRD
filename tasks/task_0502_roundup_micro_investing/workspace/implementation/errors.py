"""Error catalogue (PRD §5) and the ApiError exception type.

Every error_id and its HTTP status traces verbatim to PRD §5 "Error Code Catalogue".
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 — Error Code Catalogue. Maps error_id -> HTTP status.
ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_BUCKET_TYPE_NOT_PERMITTED": 403,
    "ERR_KYC_NOT_VERIFIED": 409,
    "ERR_BUCKET_NOT_ALLOWED_BY_PLAN": 409,
    "ERR_BENEFICIARY_REQUIRED": 400,
    "ERR_HOLD_PERIOD_ACTIVE": 409,
    "ERR_REFERRAL_WINDOW": 409,
    "ERR_SELF_REFERRAL": 409,
    "ERR_MIN_SPEND_NOT_MET": 409,
    "ERR_INSUFFICIENT_CASH": 409,
    "ERR_INSUFFICIENT_LOTS": 409,
    "ERR_IRA_CAP_EXCEEDED": 409,
    "ERR_INVALID_MULTIPLIER": 400,
    "ERR_ALLOCATION_SUM": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_BUCKET_NOT_EMPTY": 409,
    "ERR_ACCOUNT_HAS_OPEN_BUCKETS": 409,
    "ERR_DUPLICATE_TIER": 409,
    "ERR_OFFER_WINDOW_OVERLAP": 409,
    "ERR_CONTRIBUTION_DAY_COLLISION": 409,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalogue HTTP status."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)

"""Error catalogue. Error IDs and HTTP status codes come straight from PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalogue: error_id -> http status (PRD §5 / SCAFFOLD §1.6)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CORRIDOR_SUSPENDED": 409,
    "ERR_SENDER_BLOCKED": 409,
    "ERR_PAYOUT_METHOD_NOT_SUPPORTED": 409,
    "ERR_RATE_LOCK_OVERLAP": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_RECIPIENT_NOT_VERIFIED": 409,
    "ERR_KYC_DOC_REQUIRED": 422,
    "ERR_COMPLIANCE_HOLD": 409,
    "ERR_TRANSFER_NOT_FUNDED": 409,
    "ERR_PER_TRANSFER_LIMIT": 409,
    "ERR_KYC_TIER_LIMIT": 409,
    "ERR_ROLLING_WINDOW_LIMIT": 409,
    "ERR_ESCALATION_NOT_WARRANTED": 409,
    "ERR_MAX_ATTEMPTS_REACHED": 409,
    "ERR_ATTEMPTS_NOT_EXHAUSTED": 409,
    "ERR_REFUND_NOT_ALLOWED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)

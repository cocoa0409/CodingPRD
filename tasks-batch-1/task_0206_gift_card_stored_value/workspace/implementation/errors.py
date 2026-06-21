"""Error catalog. Each ApiError carries the scaffold/PRD error_id, the
human-readable message, and the HTTP status from the §5 error code table."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per the §5 Error Code Catalogue.
ERR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_REDEMPTION": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CARD_RISK_FROZEN": 409,
    "ERR_CARD_RISK_REVIEW": 409,
    "ERR_CARD_ALREADY_REPLACED": 409,
    "ERR_EXPIRATION_NOT_ALLOWED": 409,
    "ERR_DORMANCY_NOT_DUE": 409,
    "ERR_WAIVER_OVERLAP": 409,
    "ERR_CAMPAIGN_OVERLAP": 409,
    "ERR_RELOAD_BELOW_MIN": 409,
    "ERR_BALANCE_CAP_EXCEEDED": 409,
    "ERR_INSUFFICIENT_BALANCE": 409,
    "ERR_REFUND_EXCEEDS_REDEMPTION": 409,
    "ERR_NOT_CORPORATE_BUYER": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR_HTTP[error_id], message)

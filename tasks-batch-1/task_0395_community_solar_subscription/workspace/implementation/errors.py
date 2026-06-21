"""Error catalogue (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    """Carries the machine-readable error_id, http status, and a message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5 / SCAFFOLD §1.6).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_PERIOD_VERSION": 412,
    "ERR_PROJECT_FULL": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_CARVE_OUT_EXCEEDED": 409,
    "ERR_USAGE_CAP_EXCEEDED": 409,
    "ERR_TRANSFER_JURISDICTION_MISMATCH": 409,
    "ERR_METER_READING_REQUIRED": 400,
    "ERR_DISPUTE_BLOCKS_APPLY": 409,
    "ERR_OPEN_DISPUTE_BLOCKS_CLOSE": 409,
    "ERR_RECON_ALREADY_APPLIED": 409,
    "ERR_REC_BENEFICIARY_REQUIRED": 400,
    "ERR_REC_COUNTERPARTY_REQUIRED": 400,
    "ERR_WAITLIST_NOT_QUEUED": 409,
    "ERR_IMMUTABLE_RESOURCE": 409,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)

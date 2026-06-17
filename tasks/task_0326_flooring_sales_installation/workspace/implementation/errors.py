"""Error classes and error-id constants for the Flooring API."""


class ApiError(Exception):
    """Carries error_id, message, and http_status for the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (id -> http status). Single source of truth.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_PRODUCT_DISCONTINUED": 409,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_VARIANT_STATE_MISMATCH": 409,
    "ERR_VALID_UNTIL_IN_PAST": 422,
    "ERR_STALE_JOB_VERSION": 412,
    "ERR_ESTIMATE_EXPIRED": 409,
    "ERR_CREW_SKILL_MISMATCH": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_CREW_TIME_CONFLICT": 409,
    "ERR_CREW_CAPACITY_EXCEEDED": 409,
    "ERR_JOB_SLOT_OVERLAP": 409,
    "ERR_JOB_NOT_ACCEPTED": 409,
    "ERR_MATERIAL_NOT_READY": 409,
    "ERR_MATERIAL_NOT_RECEIVED": 409,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_RISK_TOO_HIGH": 409,
    "ERR_JOB_NOT_COMPLETED": 409,
    "ERR_INVALID_REQUEST": 422,
}


def err(error_id, message=None):
    """Build an ApiError using the catalogue's http status for error_id."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

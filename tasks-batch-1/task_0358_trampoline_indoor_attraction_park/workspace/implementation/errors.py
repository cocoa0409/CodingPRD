"""Error classes and the error catalogue (PRD §5)."""


class ApiError(Exception):
    """An error carrying a machine-readable error_id and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http status (PRD §5)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_GUARDIAN_REQUIRED": 422,
    "ERR_INVALID_SIGNER": 422,
    "ERR_WAIVER_MISSING_OR_EXPIRED": 422,
    "ERR_OUTSIDE_CHECKIN_WINDOW": 422,
    "ERR_ROOM_CONFLICT": 409,
    "ERR_INVALID_SLOT_WINDOW": 422,
    "ERR_GUEST_COUNT_OUT_OF_RANGE": 422,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_STALE_SLOT_VERSION": 412,
    "ERR_SLOT_CAPACITY_EXCEEDED": 409,
    "ERR_ALREADY_PAID": 409,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_RENEWAL_NOT_DUE": 409,
    "ERR_VALIDATION": 422,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    """Build an ApiError from the catalogue (status looked up by id)."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

"""Error classes and the error catalogue (PRD Section 5)."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http status (PRD Section 5).
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_PLAN_SHAPE_INVALID": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PLATE_TAKEN": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_RESOURCE_RETIRED": 409,
    "ERR_FREEZE_OVERLAP": 409,
    "ERR_COOLDOWN_ACTIVE": 409,
    "ERR_CAPACITY_FULL": 409,
    "ERR_ADDON_LIMIT": 409,
    "ERR_NO_CREDITS": 409,
    "ERR_INSUFFICIENT_WALLET": 409,
    "ERR_NO_MEMBERSHIP": 409,
    "ERR_LOCATION_CLOSED": 409,
    "ERR_OUT_OF_NETWORK": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalogue HTTP status."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

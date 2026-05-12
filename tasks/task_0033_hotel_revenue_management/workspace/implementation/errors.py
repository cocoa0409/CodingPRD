"""Error definitions and exceptions for the Hotel Revenue Management API."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_MODIFICATION_NOT_ALLOWED": 409,
    "ERR_MODIFICATION_TOO_LATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ROOM_UNAVAILABLE": 409,
    "ERR_ROOM_TYPE_MISMATCH": 422,
    "ERR_RATE_PLAN_NOT_DISTRIBUTED": 422,
    "ERR_MAINTENANCE_OVERLAP": 409,
    "ERR_ROOM_CURRENTLY_OCCUPIED": 409,
    "ERR_DUPLICATE_PRIORITY_RANK": 409,
    "ERR_INVENTORY_SHARE_EXCEEDED": 422,
    "ERR_INVENTORY_EXHAUSTED": 409,
    "ERR_OVERBOOKING_LIMIT_EXCEEDED": 409,
    "ERR_OVERRIDE_ALREADY_PENDING": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_INVALID_INPUT": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    if error_id not in ERROR_CATALOG:
        # Fall back to ERR_INVALID_INPUT for safety.
        return APIError(error_id, message or error_id, 422)
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

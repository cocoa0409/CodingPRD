"""Error definitions and exceptions."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_EQUIPMENT_UNAVAILABLE": 409,
    "ERR_AUTHORIZATION_INVALID": 422,
    "ERR_AUTHORIZATION_ALREADY_DECIDED": 409,
    "ERR_CERTIFICATE_EXPIRED": 422,
    "ERR_QUALIFICATION_NOT_MET": 422,
    "ERR_SHARING_SCOPE_VIOLATION": 422,
    "ERR_LEAD_TIME_VIOLATED": 422,
    "ERR_SLOT_GRID_VIOLATION": 422,
    "ERR_DURATION_LIMIT_EXCEEDED": 422,
    "ERR_MAINTENANCE_BLOCK": 409,
    "ERR_RESERVATION_OVERLAP": 409,
    "ERR_PEAK_PRIORITY_VIOLATION": 409,
    "ERR_FEE_SPLIT_INVALID": 422,
    "ERR_BILLING_RULE_RACED": 409,
    "ERR_NOTHING_TO_SETTLE": 422,
    "ERR_IDEMPOTENCY_CONFLICT": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_BAD_REQUEST": 400,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

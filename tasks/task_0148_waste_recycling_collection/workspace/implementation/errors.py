"""Error definitions and the APIError exception used across the service."""


class APIError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status (from PRD §5 / scaffold §1.6)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_SEQUENCE": 409,
    "ERR_HAZARD_CLASS_REQUIRED": 422,
    "ERR_NO_MATCHING_CART": 409,
    "ERR_WEIGHT_TICKET_NOT_ALLOWED": 409,
    "ERR_INVALID_PERIOD": 422,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_PICKUP_SLOT_TAKEN": 409,
    "ERR_OPEN_BALANCE": 409,
    "ERR_STOPS_PENDING": 409,
    "ERR_DRIVER_NOT_ASSIGNED": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return APIError(error_id, ERROR_CATALOG[error_id], message)

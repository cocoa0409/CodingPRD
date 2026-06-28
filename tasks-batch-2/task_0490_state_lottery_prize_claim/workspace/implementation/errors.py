"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status (PRD section 5 / scaffold 1.6)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PLAYER_SELF_EXCLUDED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_ANNUITY_NOT_ALLOWED": 422,
    "ERR_ID_VERIFICATION_REQUIRED": 422,
    "ERR_CLAIM_WINDOW_EXPIRED": 409,
    "ERR_ENTRY_NOT_ELIGIBLE": 409,
    "ERR_DRAWING_NOT_CLOSED": 409,
    "ERR_EMPTY_DRAWING_POOL": 409,
    "ERR_RETAILER_NOT_LICENSED": 409,
    "ERR_TERMINAL_NOT_ACTIVE": 409,
    "ERR_TICKET_NOT_CLAIMABLE": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_REQUEST": 422,
    "ERR_REINSTATE_TOO_EARLY": 409,
    "ERR_VALIDATION_FILTER_INVALID": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)

"""Error classes and error-ID/HTTP-status catalog (PRD §5, SCAFFOLD §1.6)."""


class APIError(Exception):
    """Carries error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_CONFIGURATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_EMPTY_ORDER": 409,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_NOT_SETTLED": 409,
    "ERR_ALREADY_SETTLED": 409,
    "ERR_FINANCING_EXISTS": 409,
    "ERR_CREDIT_TOO_LOW": 409,
    "ERR_DTI_EXCEEDED": 409,
    "ERR_TOO_MANY_OPEN_PLANS": 409,
    "ERR_NO_PERIOD_DUE": 409,
    "ERR_INSUFFICIENT_CATCH_UP": 409,
    "ERR_PAYMENT_BELOW_PAYOFF": 409,
    "ERR_WINDOW_OUT_OF_SHIFT": 422,
    "ERR_STOP_OVERLAP": 409,
    "ERR_LEAD_TIME_NOT_MET": 409,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 409,
    "ERR_ROUTE_NOT_OPEN": 409,
    "ERR_ROUTE_NOT_LOCKED": 409,
    "ERR_STOPS_UNRESOLVED": 409,
    "ERR_STOP_ACTIVE": 409,
    "ERR_LINE_NOT_RETURNABLE": 409,
    "ERR_RETURN_WINDOW_CLOSED": 409,
    "ERR_PROTECTION_NOT_ALLOWED": 409,
    "ERR_OPEN_RETURNS_EXIST": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an APIError using the catalog HTTP status for error_id."""
    return APIError(error_id, ERROR_CATALOG[error_id], message)

"""Error class and error-ID constants for the 401(k) Retirement Plan API."""


class APIError(Exception):
    """Domain error carrying error_id, HTTP status, and a human message."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"

# Existence / shape
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# State
ERR_INVALID_STATE = "ERR_INVALID_STATE"

# OCC
ERR_STALE_VERSION = "ERR_STALE_VERSION"

# Business
ERR_LOAN_ALREADY_OUTSTANDING = "ERR_LOAN_ALREADY_OUTSTANDING"
ERR_LOAN_EXCEEDS_LIMIT = "ERR_LOAN_EXCEEDS_LIMIT"
ERR_DEFERRAL_LIMIT_EXCEEDED = "ERR_DEFERRAL_LIMIT_EXCEEDED"
ERR_NO_HARDSHIP_HEADROOM = "ERR_NO_HARDSHIP_HEADROOM"
ERR_RMD_NOT_REQUIRED = "ERR_RMD_NOT_REQUIRED"
ERR_JOINT_LIFE_INELIGIBLE = "ERR_JOINT_LIFE_INELIGIBLE"
ERR_DUPLICATE_RMD_YEAR = "ERR_DUPLICATE_RMD_YEAR"

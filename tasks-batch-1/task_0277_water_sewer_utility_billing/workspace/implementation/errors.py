"""Error classes and error-id constants.

Every error_id and its HTTP status traces to PRD §5 (Error Code Catalogue)
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Raised anywhere in request handling; mapped to the standard error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authorization / ownership (PRD §2.1, §2.9)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"             # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"     # 403

# Existence / request validity (PRD §2.8)
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 422

# State / concurrency (PRD §2.9)
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_ACCOUNT_VERSION = "ERR_STALE_ACCOUNT_VERSION"  # 412

# Business rules (PRD §3)
ERR_DUPLICATE_BILL = "ERR_DUPLICATE_BILL"             # 409
ERR_READ_REGRESSION = "ERR_READ_REGRESSION"           # 422
ERR_MORATORIUM_ACTIVE = "ERR_MORATORIUM_ACTIVE"       # 409
ERR_SHUTOFF_PROTECTED = "ERR_SHUTOFF_PROTECTED"       # 409
ERR_SHUTOFF_NOT_DUE = "ERR_SHUTOFF_NOT_DUE"           # 409
ERR_BILL_NOT_POSTED = "ERR_BILL_NOT_POSTED"           # 409
ERR_ARREARS_BELOW_THRESHOLD = "ERR_ARREARS_BELOW_THRESHOLD"  # 409
ERR_NO_LEAK_VOLUME = "ERR_NO_LEAK_VOLUME"             # 422
ERR_NOT_EXECUTED = "ERR_NOT_EXECUTED"                 # 409
ERR_BILL_HAS_PAYMENT = "ERR_BILL_HAS_PAYMENT"         # 409
ERR_CYCLE_CLOSED = "ERR_CYCLE_CLOSED"                 # 409
ERR_NO_CONSUMPTION_DATA = "ERR_NO_CONSUMPTION_DATA"   # 422
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"         # 422


# error_id -> http_status (PRD §5)
HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_NOT_RESOURCE_OWNER: 403,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 422,
    ERR_INVALID_STATE: 409,
    ERR_STALE_ACCOUNT_VERSION: 412,
    ERR_DUPLICATE_BILL: 409,
    ERR_READ_REGRESSION: 422,
    ERR_MORATORIUM_ACTIVE: 409,
    ERR_SHUTOFF_PROTECTED: 409,
    ERR_SHUTOFF_NOT_DUE: 409,
    ERR_BILL_NOT_POSTED: 409,
    ERR_ARREARS_BELOW_THRESHOLD: 409,
    ERR_NO_LEAK_VOLUME: 422,
    ERR_NOT_EXECUTED: 409,
    ERR_BILL_HAS_PAYMENT: 409,
    ERR_CYCLE_CLOSED: 409,
    ERR_NO_CONSUMPTION_DATA: 422,
    ERR_VALIDATION_LIMIT: 422,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's HTTP status for error_id."""
    return ApiError(error_id, HTTP_STATUS[error_id], message)

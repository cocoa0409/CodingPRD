"""Custom error class and error catalog (PRD §5 / SCAFFOLD §1.6).

Every error_id carries a fixed HTTP status. The error response body uses the
exact field names from the response envelope: data.error_id / data.message.
"""

# error_id -> http_status (PRD §5 Error Code Catalogue)
ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE": 409,
    "ERR_DISCLOSURE_NOT_ACCEPTED": 409,
    "ERR_SETTLEMENT_HOLD_ACTIVE": 409,
    "ERR_NOT_DELINQUENT": 409,
    "ERR_LOAN_HAS_PAYMENTS": 409,
    "ERR_INSUFFICIENT_CREDIT": 409,
    "ERR_STALE_VERSION": 412,
}


class APIError(Exception):
    """An error that maps to the standard error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)


def err(error_id, message=None):
    return APIError(error_id, message)

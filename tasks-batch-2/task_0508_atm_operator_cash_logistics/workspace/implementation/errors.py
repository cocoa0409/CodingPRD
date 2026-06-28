"""Error catalog and the ApiError exception type.

Every error_id and its HTTP status come straight from SCAFFOLD.yaml §1.6 /
PRD §5. The exception carries error_id + message + http_status so the global
handler can render the standard error envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) — authoritative catalog.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_TICKET_OWNER": 403,
    "ERR_SURCHARGE_CAP_EXCEEDED": 422,
    "ERR_ACK_TEXT_MISSING": 422,
    "ERR_DISCLOSURE_MISMATCH": 422,
    "ERR_NO_FEE_DISCLOSURE": 422,
    "ERR_ATM_OUT_OF_SERVICE": 409,
    "ERR_ROUTE_PAUSED": 409,
    "ERR_AMOUNT_NOT_DENOMINATED": 422,
    "ERR_ROUTE_WINDOW_CONFLICT": 409,
    "ERR_ATM_SERVICE_LOCKOUT": 409,
    "ERR_VAULT_INSUFFICIENT": 422,
    "ERR_TXN_ALREADY_SETTLED": 409,
    "ERR_MERCHANT_SUSPENDED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    """Build an ApiError, resolving the http status from the catalog."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)

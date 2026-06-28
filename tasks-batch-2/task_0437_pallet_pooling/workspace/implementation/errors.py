"""Error catalogue (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    """An error carrying the scaffold-defined error_id, message and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD §5 Error Code Catalogue / scaffold §1.6)
ERROR_HTTP = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_HAS_OPEN_HIRE": 409,
    "ERR_ACCOUNT_NOT_SETTLED": 409,
    "ERR_ASSET_NOT_AVAILABLE": 409,
    "ERR_ASSET_NOT_DAMAGED": 409,
    "ERR_ASSET_WRONG_LOCATION": 409,
    "ERR_LOCATION_CLOSED": 409,
    "ERR_AUDIT_WINDOW_OVERLAP": 409,
    "ERR_VOUCHER_EXPIRED": 409,
    "ERR_VOUCHER_REDEEM_LOCATION_INVALID": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 409,
    "ERR_HIRE_NOT_CLOSED": 409,
    "ERR_HIRE_ALREADY_INVOICED": 409,
    "ERR_INVOICE_EMPTY": 409,
    "ERR_ASSET_TYPE_DISCONTINUED": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)

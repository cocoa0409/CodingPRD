"""APIError exception and the error catalog."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_VALIDATION": 422,
    "ERR_ACCOUNT_CLOSED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_CATEGORY_NOT_ACTIVATABLE": 422,
    "ERR_ACTIVATION_WINDOW_CLOSED": 422,
    "ERR_ACTIVATION_ALREADY_EXISTS": 409,
    "ERR_INVALID_TRANSFER_INCREMENT": 422,
    "ERR_PARTNER_INACTIVE": 422,
    "ERR_INSUFFICIENT_POINTS": 422,
    "ERR_BELOW_MINIMUM_REDEMPTION": 422,
    "ERR_INVALID_REDEMPTION_BODY": 422,
    "ERR_REFUND_MISMATCH": 422,
    "ERR_PARTIAL_REFUND_DISALLOWED": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

"""Error definitions and exception class."""


class APIError(Exception):
    """An error that should be serialized as a JSON error envelope."""

    def __init__(self, error_id: str, message: str = "", http_status: int = 400):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status


# Error ID constants and their HTTP status mappings.
ERROR_HTTP_STATUS = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_SESSION_STATE": 409,
    "ERR_PILE_UNAVAILABLE": 409,
    "ERR_PILE_HAS_DEPENDENTS": 409,
    "ERR_PILE_ALREADY_RESERVED": 409,
    "ERR_RESERVATION_EXPIRED": 409,
    "ERR_RESERVATION_MISMATCH": 422,
    "ERR_QUEUE_NOT_AT_FRONT": 409,
    "ERR_CURVE_NON_MONOTONIC": 422,
    "ERR_PRICING_WINDOW_OVERLAP": 409,
    "ERR_TOU_WINDOWS_OVERLAP": 422,
    "ERR_NO_SHOW_THRESHOLD_EXCEEDED": 409,
    "ERR_INSUFFICIENT_BALANCE": 402,
    "ERR_SETTLEMENT_OVER_ALLOCATION": 422,
    "ERR_INVALID_PAYOUT_WINDOW": 422,
    "ERR_PAYOUT_NEGATIVE_NET": 409,
    "ERR_PAYOUT_PERIOD_DRIFT": 409,
    "ERR_VALIDATION": 422,
}


def raise_error(error_id: str, message: str = "") -> None:
    http_status = ERROR_HTTP_STATUS.get(error_id, 400)
    raise APIError(error_id, message or error_id, http_status)

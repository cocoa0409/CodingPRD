"""Error catalog and ApiError exception class."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID -> HTTP status. Matches PRD §5 exactly.
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STOREFRONT_CHANNEL_ALREADY_LINKED": 409,
    "ERR_DESIGN_DUPLICATE_HASH": 409,
    "ERR_STALE_STOREFRONT_VERSION": 412,
    "ERR_CREATOR_NOT_VERIFIED": 403,
    "ERR_STRIKE_THRESHOLD_EXCEEDED": 422,
    "ERR_DESIGN_CREATOR_MISMATCH": 422,
    "ERR_LISTING_NOT_AVAILABLE": 422,
    "ERR_SAMPLE_LIMIT_EXCEEDED": 422,
    "ERR_MARKUP_OUT_OF_RANGE": 422,
    "ERR_PAYOUT_WINDOW_OVERLAP": 422,
    "ERR_NO_ELIGIBLE_PARTNER": 422,
    "ERR_REFUND_AMOUNT_INVALID": 422,
    "ERR_PAYOUT_ZERO_GROSS": 422,
    "ERR_PAYOUT_RETURN_WINDOW_EXPIRED": 422,
    "ERR_REPRINT_ORDER_NOT_SHIPPED": 422,
    "ERR_INVALID_REQUEST": 400,
}


def raise_error(error_id, message=""):
    http = ERROR_HTTP.get(error_id, 400)
    if not message:
        message = error_id
    raise ApiError(error_id, message, http)

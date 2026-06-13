"""Error classes and error-id constants.

Every error_id and HTTP status is taken verbatim from PRD §5 (error catalogue)
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status (PRD §5)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_SELLER_NOT_ACTIVE = ("ERR_SELLER_NOT_ACTIVE", 409)
ERR_STALE_SELLER_VERSION = ("ERR_STALE_SELLER_VERSION", 412)
ERR_BELOW_1099K_THRESHOLD = ("ERR_BELOW_1099K_THRESHOLD", 422)
ERR_REFUND_EXCEEDS_REMAINING = ("ERR_REFUND_EXCEEDS_REMAINING", 422)
ERR_ORDER_ALREADY_CLAWED = ("ERR_ORDER_ALREADY_CLAWED", 409)
ERR_REPRESENTMENT_WINDOW_CLOSED = ("ERR_REPRESENTMENT_WINDOW_CLOSED", 422)
ERR_DISPUTE_ROUND_EXHAUSTED = ("ERR_DISPUTE_ROUND_EXHAUSTED", 422)
ERR_NOTHING_TO_PAY = ("ERR_NOTHING_TO_PAY", 422)
ERR_BAD_MICRO_DEPOSIT_CODE = ("ERR_BAD_MICRO_DEPOSIT_CODE", 422)
ERR_OPEN_BALANCE_BLOCKS_CLOSE = ("ERR_OPEN_BALANCE_BLOCKS_CLOSE", 409)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_NO_VERIFIED_PAYOUT_METHOD = ("ERR_NO_VERIFIED_PAYOUT_METHOD", 422)
ERR_VALIDATION_PAGINATION = ("ERR_VALIDATION_PAGINATION", 400)


def err(spec, message=None):
    """Build an ApiError from one of the (error_id, http) tuples above."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)

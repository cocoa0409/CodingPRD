"""Error catalogue and ApiError exception (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE": 409,
    "ERR_PROMO_CONFIG_INVALID": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_CART_NOT_OPEN": 409,
    "ERR_CART_NOT_PRICED": 409,
    "ERR_PROMO_NOT_REDEEMABLE": 409,
    "ERR_NOT_ELIGIBLE": 403,
    "ERR_STACKING_CONFLICT": 409,
    "ERR_COUPON_DISABLED": 409,
    "ERR_COUPON_EXHAUSTED": 409,
    "ERR_ABUSE_LIMIT_EXCEEDED": 409,
    "ERR_PROMO_BUDGET_WOULD_EXCEED": 409,
    "ERR_PROMO_BUDGET_EXHAUSTED": 409,
    "ERR_PROMO_HAS_RESERVATIONS": 409,
    "ERR_STALE_CART_VERSION": 412,
    "ERR_STALE_PROMOTION_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalogue's HTTP status."""
    return ApiError(error_id, ERRORS[error_id], message)

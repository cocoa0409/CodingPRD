"""Error catalog and ApiError exception (SCAFFOLD.yaml §1.6 / PRD §5)."""

# error_id -> HTTP status (verbatim from PRD §5 Error Code Catalogue)
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_MOLD_NOT_FOUND": 404,
    "ERR_CUSTOM_ORDER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_TEMPERING_LINE_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_OWNERSHIP_FORBIDDEN": 403,
    "ERR_ACCOUNT_TYPE_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ALLERGEN_RESTRICTED": 422,
    "ERR_TEMPERING_LINE_CONFLICT": 409,
    "ERR_MOLD_CAPACITY_EXCEEDED": 409,
    "ERR_FULFILLMENT_WINDOW_CLOSED": 422,
    "ERR_MOLD_INACTIVE": 409,
    "ERR_BATCH_EXPIRED": 409,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_BUNDLE_COMPONENT_INVALID": 422,
    "ERR_DUPLICATE_LINE": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id

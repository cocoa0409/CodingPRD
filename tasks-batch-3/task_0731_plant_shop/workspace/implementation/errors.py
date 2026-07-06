"""Error IDs and the ApiError exception carrying error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# From SCAFFOLD.yaml §1.6 and PRD §5
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_STOCK_UNAVAILABLE = "ERR_STOCK_UNAVAILABLE"
ERR_STOCK_UNIT_UNHEALTHY = "ERR_STOCK_UNIT_UNHEALTHY"
ERR_INSUFFICIENT_LOYALTY = "ERR_INSUFFICIENT_LOYALTY"
ERR_WARRANTY_EXPIRED = "ERR_WARRANTY_EXPIRED"
ERR_WARRANTY_NOT_ELIGIBLE = "ERR_WARRANTY_NOT_ELIGIBLE"
ERR_WORKSHOP_FULL = "ERR_WORKSHOP_FULL"
ERR_WORKSHOP_OVERLAP = "ERR_WORKSHOP_OVERLAP"
ERR_WORKSHOP_TOO_LATE = "ERR_WORKSHOP_TOO_LATE"
ERR_DELIVERY_OVERLAP = "ERR_DELIVERY_OVERLAP"
ERR_DELIVERY_OUT_OF_ZONE = "ERR_DELIVERY_OUT_OF_ZONE"
ERR_SPECIAL_ORDER_INVALID_STATE = "ERR_SPECIAL_ORDER_INVALID_STATE"
ERR_SUBSCRIPTION_INACTIVE = "ERR_SUBSCRIPTION_INACTIVE"
ERR_SUBSCRIPTION_MISSING_STOCK = "ERR_SUBSCRIPTION_MISSING_STOCK"
ERR_REFUND_CAP_EXCEEDED = "ERR_REFUND_CAP_EXCEEDED"


def not_found(what: str = "resource"):
    return ApiError(ERR_NOT_FOUND, 404, f"{what} not found")


def invalid_request(message: str):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message: str):
    return ApiError(ERR_INVALID_STATE, 409, message)


def unauthenticated(message: str = "missing or invalid auth"):
    return ApiError(ERR_UNAUTHENTICATED, 401, message)


def unauthorized(message: str = "not permitted"):
    return ApiError(ERR_UNAUTHORIZED, 403, message)


def stale_version(message: str = "stale version"):
    return ApiError(ERR_STALE_VERSION, 412, message)

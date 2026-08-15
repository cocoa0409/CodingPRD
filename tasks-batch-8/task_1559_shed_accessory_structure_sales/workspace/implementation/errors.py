"""Error classes and error ID constants (SCAFFOLD Table 6 / PRD §5)."""


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_STALE_RULE_SET = "ERR_STALE_RULE_SET"
ERR_ANCHOR_REQUIRED = "ERR_ANCHOR_REQUIRED"
ERR_CONFIG_OUT_OF_BOUNDS = "ERR_CONFIG_OUT_OF_BOUNDS"
ERR_DELIVERY_MODE_UNSUPPORTED = "ERR_DELIVERY_MODE_UNSUPPORTED"
ERR_DATE_IN_PAST = "ERR_DATE_IN_PAST"
ERR_ASSESSOR_WINDOW_CONFLICT = "ERR_ASSESSOR_WINDOW_CONFLICT"
ERR_CREW_DATE_CONFLICT = "ERR_CREW_DATE_CONFLICT"
ERR_DEPOSIT_INSUFFICIENT = "ERR_DEPOSIT_INSUFFICIENT"
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"
ERR_ORDER_NOT_PAYABLE = "ERR_ORDER_NOT_PAYABLE"
ERR_ORDER_NOT_COMPLETED = "ERR_ORDER_NOT_COMPLETED"
ERR_IDEMPOTENCY_CONFLICT = "ERR_IDEMPOTENCY_CONFLICT"


class ApiError(Exception):
    """An API error carrying its catalog error_id and HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(message: str = "Missing or invalid X-User-Role or X-User-ID headers") -> ApiError:
    return ApiError(ERR_UNAUTHENTICATED, message, 401)


def forbidden(message: str = "Role not permitted on endpoint") -> ApiError:
    return ApiError(ERR_FORBIDDEN, message, 403)


def not_found(message: str = "Referenced resource does not exist") -> ApiError:
    return ApiError(ERR_NOT_FOUND, message, 404)


def invalid_request(message: str = "Missing required field, malformed value, or invalid enum member") -> ApiError:
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def invalid_state(message: str = "Resource not in a state that allows the requested transition") -> ApiError:
    return ApiError(ERR_INVALID_STATE, message, 409)

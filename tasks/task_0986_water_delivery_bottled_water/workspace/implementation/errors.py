"""Error catalog: exact error_ids and HTTP statuses from the scaffold/PRD."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_INVALID_REFERENCE = "ERR_INVALID_REFERENCE"        # 422
ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"      # 422
ERR_DUPLICATE_SEQUENCE = "ERR_DUPLICATE_SEQUENCE"      # 409
ERR_ROUTE_CAPACITY_EXCEEDED = "ERR_ROUTE_CAPACITY_EXCEEDED"  # 422
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                    # 422
ERR_OUTSTANDING_BALANCE = "ERR_OUTSTANDING_BALANCE"    # 422
ERR_BOTTLES_OUTSTANDING = "ERR_BOTTLES_OUTSTANDING"    # 422
ERR_SKIP_REASON_REQUIRED = "ERR_SKIP_REASON_REQUIRED"  # 400
ERR_CREDIT_EXPIRED = "ERR_CREDIT_EXPIRED"              # 422
ERR_INVALID_PRICING_CONFIG = "ERR_INVALID_PRICING_CONFIG"  # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"          # 409


def unauthenticated(msg="missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="role not permitted to invoke this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def forbidden(msg="customer may only act on own resources"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)


def invalid_reference(msg):
    return ApiError(ERR_INVALID_REFERENCE, 422, msg)


def invalid_date_range(msg):
    return ApiError(ERR_INVALID_DATE_RANGE, 422, msg)

"""Error classes and error-id constants.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog (error_id -> http_status)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                     # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                     # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"        # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                     # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
ERR_PRODUCT_MISMATCH = "ERR_PRODUCT_MISMATCH"      # 409
ERR_STALE_ROAST = "ERR_STALE_ROAST"                # 409
ERR_RELEASE_NOT_DUE = "ERR_RELEASE_NOT_DUE"        # 409
ERR_INSUFFICIENT_GREEN = "ERR_INSUFFICIENT_GREEN"  # 409
ERR_INSUFFICIENT_ROASTED = "ERR_INSUFFICIENT_ROASTED"  # 409
ERR_WEIGHT_GAIN = "ERR_WEIGHT_GAIN"                # 409
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"  # 409
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"            # 412


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is missing or malformed"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def duplicate(msg="Resource violates a uniqueness constraint"):
    return ApiError(ERR_DUPLICATE, 409, msg)


def invalid_state(msg="Resource is not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def product_mismatch(msg="Product reference incompatible"):
    return ApiError(ERR_PRODUCT_MISMATCH, 409, msg)


def stale_roast(msg="Roasted lot exceeds the effective freshness ceiling"):
    return ApiError(ERR_STALE_ROAST, 409, msg)


def release_not_due(msg="Standing order release is not due yet"):
    return ApiError(ERR_RELEASE_NOT_DUE, 409, msg)


def insufficient_green(msg="Not enough green on hand"):
    return ApiError(ERR_INSUFFICIENT_GREEN, 409, msg)


def insufficient_roasted(msg="Not enough roasted stock available"):
    return ApiError(ERR_INSUFFICIENT_ROASTED, 409, msg)


def weight_gain(msg="Roasted weight cannot exceed green weight"):
    return ApiError(ERR_WEIGHT_GAIN, 409, msg)


def credit_limit_exceeded(msg="Credit ceiling exceeded or account not active"):
    return ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 409, msg)


def overpayment(msg="Payment amount is not within the allowed range"):
    return ApiError(ERR_OVERPAYMENT, 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)

"""Error classes and error-id constants for the School Fundraising Booster API.

Error catalog — PRD §5 / scaffold §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"            # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                    # 422
ERR_STALE_CAMPAIGN_VERSION = "ERR_STALE_CAMPAIGN_VERSION"      # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                        # 409
ERR_CAMPAIGN_NOT_ACTIVE = "ERR_CAMPAIGN_NOT_ACTIVE"            # 409
ERR_SELLER_BLOCKED = "ERR_SELLER_BLOCKED"                      # 409
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"              # 409
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"                        # 409
ERR_DUPLICATE_KEY = "ERR_DUPLICATE_KEY"                        # 409
ERR_PAID_ORDER_NOT_CANCELLABLE = "ERR_PAID_ORDER_NOT_CANCELLABLE"  # 409


def unauthenticated(msg="Missing or malformed X-User-ID / X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="Referenced resource not found or not in the named campaign"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def stale_campaign_version(msg="expected_campaign_version does not match current campaign version"):
    return ApiError(ERR_STALE_CAMPAIGN_VERSION, 412, msg)


def invalid_state(msg="Resource is not in a legal state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def campaign_not_active(msg="Campaign posture does not permit this child operation"):
    return ApiError(ERR_CAMPAIGN_NOT_ACTIVE, 409, msg)


def seller_blocked(msg="Crediting seller is BLOCKED"):
    return ApiError(ERR_SELLER_BLOCKED, 409, msg)


def insufficient_stock(msg="Order line requests more units than available headroom"):
    return ApiError(ERR_INSUFFICIENT_STOCK, 409, msg)


def shift_overlap(msg="Booking overlaps another BOOKED shift of the same volunteer"):
    return ApiError(ERR_SHIFT_OVERLAP, 409, msg)


def duplicate_key(msg="Unique key already exists within campaign"):
    return ApiError(ERR_DUPLICATE_KEY, 409, msg)


def paid_order_not_cancellable(msg="Cannot cancel a PAID order; refund it instead"):
    return ApiError(ERR_PAID_ORDER_NOT_CANCELLABLE, 409, msg)

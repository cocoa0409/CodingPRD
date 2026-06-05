"""Error classes and error ID constants (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authorization
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
# Existence
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"    # 404
ERR_JURISDICTION_NOT_FOUND = "ERR_JURISDICTION_NOT_FOUND"  # 404
# Body / uniqueness
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                        # 409
# State / business
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_PLAN_ARCHIVED = "ERR_PLAN_ARCHIVED"                # 409
ERR_COUPON_NOT_REDEEMABLE = "ERR_COUPON_NOT_REDEEMABLE"  # 409
ERR_NO_PLAN_CHANGE = "ERR_NO_PLAN_CHANGE"              # 409
ERR_USAGE_OUT_OF_PERIOD = "ERR_USAGE_OUT_OF_PERIOD"    # 409
ERR_ADDON_ALREADY_ACTIVE = "ERR_ADDON_ALREADY_ACTIVE"  # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_ACCOUNT_HAS_ACTIVE_SUBS = "ERR_ACCOUNT_HAS_ACTIVE_SUBS"  # 409
ERR_ACCOUNT_HAS_OPEN_INVOICES = "ERR_ACCOUNT_HAS_OPEN_INVOICES"  # 409
ERR_PRICE_SCHEDULE_OVERLAP = "ERR_PRICE_SCHEDULE_OVERLAP"  # 409
ERR_PAUSE_WINDOW_CONFLICT = "ERR_PAUSE_WINDOW_CONFLICT"  # 409
ERR_VALIDATION_RANGE = "ERR_VALIDATION_RANGE"          # 422


def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role is not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="Referenced resource not found"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def jurisdiction_not_found(msg="No tax jurisdiction matches the region_code"):
    return ApiError(ERR_JURISDICTION_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is malformed"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def duplicate(msg="Uniqueness constraint violated"):
    return ApiError(ERR_DUPLICATE, 409, msg)


def invalid_state(msg="Operation not allowed from the current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def validation_range(msg="Pagination parameter out of range"):
    return ApiError(ERR_VALIDATION_RANGE, 422, msg)

"""Error classes and error ID constants per PRD §5 error catalogue."""


class APIError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCED_NOT_FOUND = "ERR_REFERENCED_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SELF_OVERRIDE_FORBIDDEN = "ERR_SELF_OVERRIDE_FORBIDDEN"
ERR_ACCOUNT_INACTIVE = "ERR_ACCOUNT_INACTIVE"
ERR_AREA_RESTRICTED = "ERR_AREA_RESTRICTED"
ERR_PRODUCT_DISCONTINUED = "ERR_PRODUCT_DISCONTINUED"
ERR_INVALID_QUANTITY = "ERR_INVALID_QUANTITY"
ERR_INVALID_PRODUCT_SPEC = "ERR_INVALID_PRODUCT_SPEC"
ERR_WINDOW_CLOSED_FOR_SCHEDULING = "ERR_WINDOW_CLOSED_FOR_SCHEDULING"
ERR_SUBSCRIPTION_OUT_OF_SEASON = "ERR_SUBSCRIPTION_OUT_OF_SEASON"
ERR_WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"
ERR_WINDOW_CAPACITY_EXCEEDED = "ERR_WINDOW_CAPACITY_EXCEEDED"
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"
ERR_CAPACITY_MISMATCH = "ERR_CAPACITY_MISMATCH"
ERR_NOT_CANCELLABLE = "ERR_NOT_CANCELLABLE"
ERR_SUBSCRIPTION_MISMATCH = "ERR_SUBSCRIPTION_MISMATCH"
ERR_MOISTURE_CHECK_FAILED = "ERR_MOISTURE_CHECK_FAILED"
ERR_INVALID_REFUND_AMOUNT = "ERR_INVALID_REFUND_AMOUNT"
ERR_INVOICE_NOT_VOIDABLE = "ERR_INVOICE_NOT_VOIDABLE"
ERR_OUTSTANDING_REFUND = "ERR_OUTSTANDING_REFUND"
ERR_NO_ROUTE = "ERR_NO_ROUTE"
ERR_SUBSCRIPTION_ACTIVE_EXISTS = "ERR_SUBSCRIPTION_ACTIVE_EXISTS"
ERR_VALIDATION = "ERR_VALIDATION"


def unauthenticated(message="Missing or invalid auth headers"):
    return APIError(ERR_UNAUTHENTICATED, message, 401)


def unauthorized(message="Role not permitted for this endpoint"):
    return APIError(ERR_UNAUTHORIZED, message, 403)


def not_found(message="Resource not found"):
    return APIError(ERR_NOT_FOUND, message, 404)


def referenced_not_found(message="Referenced resource not found"):
    return APIError(ERR_REFERENCED_NOT_FOUND, message, 404)


def invalid_state(message="Current state does not permit the requested transition"):
    return APIError(ERR_INVALID_STATE, message, 409)


def stale_version(message="Stale version"):
    return APIError(ERR_STALE_VERSION, message, 412)


def self_override(message="Driver may not override own recent failure"):
    return APIError(ERR_SELF_OVERRIDE_FORBIDDEN, message, 403)


def account_inactive(message="Customer account is not ACTIVE"):
    return APIError(ERR_ACCOUNT_INACTIVE, message, 409)


def area_restricted(message="Product restricted in delivery area"):
    return APIError(ERR_AREA_RESTRICTED, message, 422)


def product_discontinued(message="Product is discontinued"):
    return APIError(ERR_PRODUCT_DISCONTINUED, message, 422)


def invalid_quantity(message="Quantity violates granularity rule"):
    return APIError(ERR_INVALID_QUANTITY, message, 422)


def invalid_product_spec(message="Invalid product specification"):
    return APIError(ERR_INVALID_PRODUCT_SPEC, message, 422)


def window_closed(message="Window not available for scheduling"):
    return APIError(ERR_WINDOW_CLOSED_FOR_SCHEDULING, message, 422)


def subscription_out_of_season(message="Subscription out of season"):
    return APIError(ERR_SUBSCRIPTION_OUT_OF_SEASON, message, 422)


def window_overlap(message="Window overlaps an existing window on this route and date"):
    return APIError(ERR_WINDOW_OVERLAP, message, 409)


def window_capacity(message="Window capacity would be exceeded"):
    return APIError(ERR_WINDOW_CAPACITY_EXCEEDED, message, 422)


def insufficient_stock(message="Insufficient stock"):
    return APIError(ERR_INSUFFICIENT_STOCK, message, 422)


def capacity_mismatch(message="Window capacity exceeds route capacity"):
    return APIError(ERR_CAPACITY_MISMATCH, message, 422)


def not_cancellable(message="Order cannot be cancelled from its current state"):
    return APIError(ERR_NOT_CANCELLABLE, message, 409)


def subscription_mismatch(message="Subscription belongs to a different customer"):
    return APIError(ERR_SUBSCRIPTION_MISMATCH, message, 422)


def moisture_check_failed(message="Missing or failed moisture reading"):
    return APIError(ERR_MOISTURE_CHECK_FAILED, message, 422)


def invalid_refund_amount(message="Invalid refund amount"):
    return APIError(ERR_INVALID_REFUND_AMOUNT, message, 422)


def invoice_not_voidable(message="Invoice is not voidable"):
    return APIError(ERR_INVOICE_NOT_VOIDABLE, message, 409)


def outstanding_refund(message="Outstanding refund must be settled first"):
    return APIError(ERR_OUTSTANDING_REFUND, message, 409)


def no_route(message="No route matches the delivery postal code"):
    return APIError(ERR_NO_ROUTE, message, 422)


def subscription_active_exists(message="Customer already has an ACTIVE subscription for this season"):
    return APIError(ERR_SUBSCRIPTION_ACTIVE_EXISTS, message, 409)


def validation(message="Validation failed"):
    return APIError(ERR_VALIDATION, message, 422)

"""Error classes and error-id constants.

Every error_id and http_status below is taken verbatim from SCAFFOLD.yaml
section 1.6 / PRD section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth / generic ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"    # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409

# --- sales order / billing ---
ERR_ORDER_ALREADY_BILLED = "ERR_ORDER_ALREADY_BILLED"  # 409
ERR_ORDER_NOT_FULFILLED = "ERR_ORDER_NOT_FULFILLED"    # 409
ERR_NOT_NET_TERM_ORDER = "ERR_NOT_NET_TERM_ORDER"      # 409
ERR_EMPTY_ORDER = "ERR_EMPTY_ORDER"                    # 409
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"      # 409
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"  # 409
ERR_INVOICE_NOT_FOUND = "ERR_INVOICE_NOT_FOUND"        # 409
ERR_PRODUCT_DISCONTINUED = "ERR_PRODUCT_DISCONTINUED"  # 409
ERR_ACCOUNT_SUSPENDED = "ERR_ACCOUNT_SUSPENDED"        # 409
ERR_STALE_ORDER_VERSION = "ERR_STALE_ORDER_VERSION"    # 412

# --- service ---
ERR_CYLINDER_NOT_CERTIFIED = "ERR_CYLINDER_NOT_CERTIFIED"  # 409
ERR_STATION_OFFLINE = "ERR_STATION_OFFLINE"                # 409
ERR_STATION_BOOKING_CONFLICT = "ERR_STATION_BOOKING_CONFLICT"  # 409

# --- vendor / special / purchase ---
ERR_VENDOR_NOT_DROP_SHIP = "ERR_VENDOR_NOT_DROP_SHIP"  # 409
ERR_VENDOR_INACTIVE = "ERR_VENDOR_INACTIVE"            # 409
ERR_EMPTY_PURCHASE_ORDER = "ERR_EMPTY_PURCHASE_ORDER"  # 409

# --- rental ---
ERR_RENTAL_OVERLAP = "ERR_RENTAL_OVERLAP"            # 409
ERR_RENTAL_NOT_STARTED = "ERR_RENTAL_NOT_STARTED"    # 409
ERR_ASSET_UNAVAILABLE = "ERR_ASSET_UNAVAILABLE"      # 409


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Acting role is not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Missing, malformed, or out-of-range field"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def duplicate(msg="Resource already exists"):
    return ApiError(ERR_DUPLICATE_RESOURCE, 409, msg)


def invalid_state(msg="Transition is not defined from the current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)

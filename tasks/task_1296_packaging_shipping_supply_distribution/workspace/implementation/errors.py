"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error catalog ---------------------------------------------------------
def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted on this endpoint, or acting on another account's resource."):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Referenced resource id does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Malformed payload."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Transition not defined from the resource's current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_account_suspended(msg="Account is suspended."):
    return ApiError("ERR_ACCOUNT_SUSPENDED", 409, msg)


def err_order_empty(msg="Order contains no OPEN lines."):
    return ApiError("ERR_ORDER_EMPTY", 422, msg)


def err_po_required(msg="CORPORATE account with po_required must supply po_number."):
    return ApiError("ERR_PO_REQUIRED", 422, msg)


def err_duplicate_po(msg="po_number already used by another order of this account."):
    return ApiError("ERR_DUPLICATE_PO", 409, msg)


def err_case_qty_mismatch(msg="Line qty is not a multiple of the product's case_qty."):
    return ApiError("ERR_CASE_QTY_MISMATCH", 422, msg)


def err_artwork_required(msg="Custom-print line requires print_artwork_ref and over_under_tolerance_pct within 0..20."):
    return ApiError("ERR_ARTWORK_REQUIRED", 422, msg)


def err_duplicate_subscription(msg="An ACTIVE restock subscription already exists for this (account_id, product_id)."):
    return ApiError("ERR_DUPLICATE_SUBSCRIPTION", 409, msg)


def err_no_warehouse_capable(msg="No warehouse can source this line."):
    return ApiError("ERR_NO_WAREHOUSE_CAPABLE", 422, msg)


def err_backorder_not_allowed(msg="Line cannot be covered and inventory is not backorderable."):
    return ApiError("ERR_BACKORDER_NOT_ALLOWED", 422, msg)


def err_credit_limit_exceeded(msg="open_receivable + grand_total would exceed credit_limit."):
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 422, msg)


def err_return_window_expired(msg="Return was requested more than 30 calendar days ago."):
    return ApiError("ERR_RETURN_WINDOW_EXPIRED", 422, msg)


def err_return_line_mismatch(msg="Return line references an order line of a different order."):
    return ApiError("ERR_RETURN_LINE_MISMATCH", 422, msg)


def err_custom_not_returnable(msg="Return type does not match the custom-print nature of its lines."):
    return ApiError("ERR_CUSTOM_NOT_RETURNABLE", 422, msg)


def err_custom_production_started(msg="Custom-print production has already started; cancel blocked."):
    return ApiError("ERR_CUSTOM_PRODUCTION_STARTED", 409, msg)


def err_return_qty_exceeded(msg="Return line qty exceeds shipped_qty minus prior non-rejected returns."):
    return ApiError("ERR_RETURN_QTY_EXCEEDED", 422, msg)


def err_overlapping_price_window(msg="Quantity break price window overlaps an existing break for the same product and min_qty."):
    return ApiError("ERR_OVERLAPPING_PRICE_WINDOW", 422, msg)


def err_press_occupied(msg="Starting the job would exceed the warehouse's press occupancy budget."):
    return ApiError("ERR_PRESS_OCCUPIED", 409, msg)


def err_stale_version(msg="Expected version does not match the resource's current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)

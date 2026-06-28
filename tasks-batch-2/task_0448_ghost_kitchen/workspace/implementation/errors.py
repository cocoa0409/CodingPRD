"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    """Carries error_id, message, and http_status for the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs and their HTTP statuses (exact from scaffold §1.6).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_DUPLICATE_ORDER = "ERR_DUPLICATE_ORDER"          # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"             # 409
ERR_DUPLICATE_PRIORITY_RANK = "ERR_DUPLICATE_PRIORITY_RANK"  # 409
ERR_BRAND_NOT_LISTED = "ERR_BRAND_NOT_LISTED"       # 409
ERR_NO_ELIGIBLE_STALL = "ERR_NO_ELIGIBLE_STALL"     # 409
ERR_BOOKING_OVERLAP = "ERR_BOOKING_OVERLAP"         # 409
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"  # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"             # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"         # 422


def unauthenticated(msg=None):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg or "Missing or invalid authentication headers.")


def forbidden(msg=None):
    return ApiError(ERR_FORBIDDEN, 403, msg or "Caller is not permitted to perform this operation.")


def not_found(msg=None):
    return ApiError(ERR_NOT_FOUND, 404, msg or "Referenced resource does not exist.")


def duplicate_order(msg=None):
    return ApiError(ERR_DUPLICATE_ORDER, 409, msg or "An order with this aggregator/external_ref already exists.")


def invalid_state(msg=None):
    return ApiError(ERR_INVALID_STATE, 409, msg or "Requested transition is not defined from the current state.")


def duplicate_priority_rank(msg=None):
    return ApiError(ERR_DUPLICATE_PRIORITY_RANK, 409,
                    msg or "Another ACTIVE lease at this stall already holds this priority_rank.")


def brand_not_listed(msg=None):
    return ApiError(ERR_BRAND_NOT_LISTED, 409, msg or "Brand must be ACTIVE and LISTED to route orders.")


def no_eligible_stall(msg=None):
    return ApiError(ERR_NO_ELIGIBLE_STALL, 409, msg or "No routing-eligible stall found for this order.")


def booking_overlap(msg=None):
    return ApiError(ERR_BOOKING_OVERLAP, 409,
                    msg or "Booking window overlaps an existing HELD booking or violates the turnaround buffer.")


def insufficient_inventory(msg=None):
    return ApiError(ERR_INSUFFICIENT_INVENTORY, 409,
                    msg or "Insufficient FIFO inventory to satisfy every recipe component.")


def stale_version(msg=None):
    return ApiError(ERR_STALE_VERSION, 412, msg or "expected_order_version does not match the order's current version.")


def invalid_request(msg=None):
    return ApiError(ERR_INVALID_REQUEST, 422, msg or "Request body failed field-shape validation.")

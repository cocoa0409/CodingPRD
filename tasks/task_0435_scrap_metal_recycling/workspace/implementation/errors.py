"""Error classes and error-id constants for the scrap-metal-recycling yard API."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (PRD §5 / SCAFFOLD §1.6) -----------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"             # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_SELLER_FROZEN = "ERR_SELLER_FROZEN"             # 409
ERR_CATEGORY_MISMATCH = "ERR_CATEGORY_MISMATCH"     # 409
ERR_GRADE_NOT_ACTIVE = "ERR_GRADE_NOT_ACTIVE"       # 409
ERR_INVALID_WEIGHT = "ERR_INVALID_WEIGHT"           # 422
ERR_CONTAINER_CAPACITY_EXCEEDED = "ERR_CONTAINER_CAPACITY_EXCEEDED"  # 409
ERR_HEDGE_OVER_REALIZED = "ERR_HEDGE_OVER_REALIZED"  # 409
ERR_TIN_REQUIRED_FOR_1099 = "ERR_TIN_REQUIRED_FOR_1099"  # 422
ERR_STALE_CONTAINER_VERSION = "ERR_STALE_CONTAINER_VERSION"  # 412
ERR_STALE_HEDGE_VERSION = "ERR_STALE_HEDGE_VERSION"  # 412
ERR_NO_LINE_ITEMS = "ERR_NO_LINE_ITEMS"             # 409
ERR_DUPLICATE_PAYOUT = "ERR_DUPLICATE_PAYOUT"       # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"         # 422


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role is not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Requested transition is not defined from the resource's current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def segregation_of_duties(msg="Payout approver must differ from the hold-clearing user."):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def seller_frozen(msg="Seller is frozen (FLAGGED/BANNED or has open theft reports)."):
    return ApiError(ERR_SELLER_FROZEN, 409, msg)


def category_mismatch(msg="Container category does not match a line item's category."):
    return ApiError(ERR_CATEGORY_MISMATCH, 409, msg)


def grade_not_active(msg="grade_code has no ACTIVE CommodityPrice row."):
    return ApiError(ERR_GRADE_NOT_ACTIVE, 409, msg)


def invalid_weight(msg="tare_weight_lb must be >= 0 and strictly less than gross_weight_lb."):
    return ApiError(ERR_INVALID_WEIGHT, 422, msg)


def container_capacity_exceeded(msg="Release would push container loaded weight past capacity."):
    return ApiError(ERR_CONTAINER_CAPACITY_EXCEEDED, 409, msg)


def hedge_over_realized(msg="Settling would realize more weight than the hedge's remaining capacity."):
    return ApiError(ERR_HEDGE_OVER_REALIZED, 409, msg)


def tin_required_for_1099(msg="CASH payout would cross the 1099 threshold but seller has no TIN."):
    return ApiError(ERR_TIN_REQUIRED_FOR_1099, 422, msg)


def stale_container_version(msg="expected_container_version does not match the container's version."):
    return ApiError(ERR_STALE_CONTAINER_VERSION, 412, msg)


def stale_hedge_version(msg="expected_hedge_version does not match the hedge's version."):
    return ApiError(ERR_STALE_HEDGE_VERSION, 412, msg)


def no_line_items(msg="weigh-out attempted on a ticket with zero line items."):
    return ApiError(ERR_NO_LINE_ITEMS, 409, msg)


def duplicate_payout(msg="A Payout already exists for the ticket."):
    return ApiError(ERR_DUPLICATE_PAYOUT, 409, msg)


def invalid_request(msg="Missing required field, bad enum, or out-of-range numeric value."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)

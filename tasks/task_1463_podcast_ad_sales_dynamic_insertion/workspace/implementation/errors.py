"""Error classes and error ID constants for the Podcast Ad Sales API.

All error IDs and HTTP statuses come from the scaffold's error catalog.
"""


class ApiError(Exception):
    """Application error carrying the error_id, message, and HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_AGENCY_MISMATCH = "ERR_AGENCY_MISMATCH"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_EPISODE_NOT_PUBLISHED = "ERR_EPISODE_NOT_PUBLISHED"
ERR_EPISODE_NOT_DUE = "ERR_EPISODE_NOT_DUE"
ERR_MEASUREMENT_WINDOW_OPEN = "ERR_MEASUREMENT_WINDOW_OPEN"
ERR_MEASUREMENT_PENDING = "ERR_MEASUREMENT_PENDING"
ERR_CAMPAIGN_NOT_ACTIVATABLE = "ERR_CAMPAIGN_NOT_ACTIVATABLE"
ERR_CAMPAIGN_NOT_EDITABLE = "ERR_CAMPAIGN_NOT_EDITABLE"
ERR_CAMPAIGN_NOT_ENDED = "ERR_CAMPAIGN_NOT_ENDED"
ERR_CAMPAIGN_NOT_ACTIVE = "ERR_CAMPAIGN_NOT_ACTIVE"
ERR_LINE_ITEM_STATE = "ERR_LINE_ITEM_STATE"
ERR_COPY_STATE = "ERR_COPY_STATE"
ERR_INVOICE_STATE = "ERR_INVOICE_STATE"
ERR_NO_APPROVED_COPY = "ERR_NO_APPROVED_COPY"
ERR_COPY_NOT_APPROVED = "ERR_COPY_NOT_APPROVED"
ERR_COPY_CAMPAIGN_MISMATCH = "ERR_COPY_CAMPAIGN_MISMATCH"
ERR_HOST_READ_REQUIRES_SHOW = "ERR_HOST_READ_REQUIRES_SHOW"
ERR_TARGET_SCOPE_INVALID = "ERR_TARGET_SCOPE_INVALID"
ERR_BRAND_SAFETY_CONFLICT = "ERR_BRAND_SAFETY_CONFLICT"
ERR_SHOW_SUSPENDED = "ERR_SHOW_SUSPENDED"
ERR_ADVERTISER_SUSPENDED = "ERR_ADVERTISER_SUSPENDED"
ERR_FLIGHT_WINDOW_INVALID = "ERR_FLIGHT_WINDOW_INVALID"
ERR_CATEGORY_EXCLUSIVE_CONFLICT = "ERR_CATEGORY_EXCLUSIVE_CONFLICT"
ERR_SLOT_CAPACITY_EXCEEDED = "ERR_SLOT_CAPACITY_EXCEEDED"
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"
ERR_MAKE_GOOD_OUTSTANDING = "ERR_MAKE_GOOD_OUTSTANDING"
ERR_MAKE_GOOD_STATE = "ERR_MAKE_GOOD_STATE"


def err_unauthenticated(message="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, message, 401)


def err_forbidden(message="Role not permitted for this endpoint, or ownership scope violated"):
    return ApiError(ERR_FORBIDDEN, message, 403)


def err_agency_mismatch(message="Acting agency does not represent the referenced advertiser"):
    return ApiError(ERR_AGENCY_MISMATCH, message, 403)


def err_not_found(message="Referenced identifier does not exist"):
    return ApiError(ERR_NOT_FOUND, message, 404)


def err_invalid(message="Request validation failed"):
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def err_stale(message="expected version does not match the stored version"):
    return ApiError(ERR_STALE_VERSION, message, 412)


def err_conflict(error_id, message):
    return ApiError(error_id, message, 409)

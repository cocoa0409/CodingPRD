"""Error classes and error-id constants for the Apparel Boutique API."""


class ApiError(Exception):
    """An error that maps to a structured API error response."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD §5 / scaffold §1.6) ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_DUPLICATE_KEY = ("ERR_DUPLICATE_KEY", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_STYLE_VERSION = ("ERR_STALE_STYLE_VERSION", 412)
ERR_ORDER_NOT_RETURNABLE_STATE = ("ERR_ORDER_NOT_RETURNABLE_STATE", 409)
ERR_RETURN_WINDOW_CLOSED = ("ERR_RETURN_WINDOW_CLOSED", 422)
ERR_STYLIST_NOT_ACTIVE = ("ERR_STYLIST_NOT_ACTIVE", 409)
ERR_STYLIST_DOUBLE_BOOKED = ("ERR_STYLIST_DOUBLE_BOOKED", 409)
ERR_ROOM_DOUBLE_BOOKED = ("ERR_ROOM_DOUBLE_BOOKED", 409)
ERR_INSUFFICIENT_INVENTORY = ("ERR_INSUFFICIENT_INVENTORY", 409)
ERR_INSUFFICIENT_STORE_CREDIT = ("ERR_INSUFFICIENT_STORE_CREDIT", 422)
ERR_MARKDOWN_NOT_EFFECTIVE = ("ERR_MARKDOWN_NOT_EFFECTIVE", 409)
ERR_EXCHANGE_UNAVAILABLE = ("ERR_EXCHANGE_UNAVAILABLE", 409)
ERR_LOOKBOOK_FROZEN = ("ERR_LOOKBOOK_FROZEN", 409)
ERR_VALIDATION_LIMIT = ("ERR_VALIDATION_LIMIT", 400)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple constant."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)

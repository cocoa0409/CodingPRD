"""Centralized error definitions for the Live Stream Schedule API."""


class APIError(Exception):
    """Base API error carrying an error_id, http status, and human message."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog — IDs and HTTP statuses match PRD §5
ERR_AUTH_REQUIRED = ("ERR_AUTH_REQUIRED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_VERSION_CONFLICT = ("ERR_VERSION_CONFLICT", 409)
ERR_STUDIO_INTERVAL_CONFLICT = ("ERR_STUDIO_INTERVAL_CONFLICT", 409)
ERR_STOCK_INSUFFICIENT = ("ERR_STOCK_INSUFFICIENT", 409)
ERR_OUT_OF_AVAILABLE_WINDOW = ("ERR_OUT_OF_AVAILABLE_WINDOW", 409)
ERR_TOO_LATE_TO_CANCEL = ("ERR_TOO_LATE_TO_CANCEL", 409)
ERR_INVALID_INTERVAL = ("ERR_INVALID_INTERVAL", 422)
ERR_QUALIFICATION_MISSING = ("ERR_QUALIFICATION_MISSING", 422)
ERR_PRODUCT_CERT_MISSING = ("ERR_PRODUCT_CERT_MISSING", 422)
ERR_PRODUCT_CATEGORY_MISMATCH = ("ERR_PRODUCT_CATEGORY_MISMATCH", 422)
ERR_PRODUCT_NOT_ON_SHELF = ("ERR_PRODUCT_NOT_ON_SHELF", 422)
ERR_LIVE_ASSOCIATION_DENIED = ("ERR_LIVE_ASSOCIATION_DENIED", 422)
ERR_STREAMER_NOT_ACTIVE = ("ERR_STREAMER_NOT_ACTIVE", 403)
ERR_STREAMER_BLOCKED = ("ERR_STREAMER_BLOCKED", 422)
ERR_DEPOSIT_UNPAID = ("ERR_DEPOSIT_UNPAID", 422)
ERR_APPEAL_WINDOW_CLOSED = ("ERR_APPEAL_WINDOW_CLOSED", 422)
ERR_REASON_REQUIRED = ("ERR_REASON_REQUIRED", 422)
ERR_PAGINATION_INVALID = ("ERR_PAGINATION_INVALID", 400)
ERR_VALIDATION_FAILED = ("ERR_VALIDATION_FAILED", 422)


def raise_err(spec, message: str = ""):
    """Raise an APIError from a (error_id, http_status) tuple."""
    error_id, http_status = spec
    raise APIError(error_id, http_status, message or error_id)

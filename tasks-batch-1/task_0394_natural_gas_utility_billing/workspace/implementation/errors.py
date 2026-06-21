"""Error classes and error ID constants for the Natural Gas Utility Billing API.

Every error ID and HTTP status traces to PRD §5 (Error Code Catalogue) and
SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries an error_id, human-readable message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD §5) ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NOT_SHUTOFF_ELIGIBLE = ("ERR_NOT_SHUTOFF_ELIGIBLE", 409)
ERR_EMERGENCY_HOLD = ("ERR_EMERGENCY_HOLD", 409)
ERR_WINTER_MORATORIUM = ("ERR_WINTER_MORATORIUM", 409)
ERR_INDEX_ROLLBACK = ("ERR_INDEX_ROLLBACK", 409)
ERR_PGA_NOT_FOUND = ("ERR_PGA_NOT_FOUND", 409)
ERR_READ_REQUIRED = ("ERR_READ_REQUIRED", 409)
ERR_MISSING_COMPLETION_INDEX = ("ERR_MISSING_COMPLETION_INDEX", 400)
ERR_STALE_ACCOUNT_VERSION = ("ERR_STALE_ACCOUNT_VERSION", 412)
ERR_ORDER_NOT_DUE = ("ERR_ORDER_NOT_DUE", 409)
ERR_RECONNECT_BALANCE_DUE = ("ERR_RECONNECT_BALANCE_DUE", 409)
ERR_RECONNECT_DEPOSIT_REQUIRED = ("ERR_RECONNECT_DEPOSIT_REQUIRED", 409)
ERR_DEPOSIT_WAIVED_NOT_PAYABLE = ("ERR_DEPOSIT_WAIVED_NOT_PAYABLE", 409)
ERR_DEPOSIT_REFUND_NOT_DUE = ("ERR_DEPOSIT_REFUND_NOT_DUE", 409)
ERR_NOT_ELIGIBLE = ("ERR_NOT_ELIGIBLE", 409)
ERR_NO_BILLS_TO_TRUE_UP = ("ERR_NO_BILLS_TO_TRUE_UP", 409)
ERR_VALIDATION_PENDING_BILLS = ("ERR_VALIDATION_PENDING_BILLS", 409)
ERR_BILLING_PERIOD_OVERLAP = ("ERR_BILLING_PERIOD_OVERLAP", 409)
ERR_BUDGET_PERIOD_OVERLAP = ("ERR_BUDGET_PERIOD_OVERLAP", 409)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)

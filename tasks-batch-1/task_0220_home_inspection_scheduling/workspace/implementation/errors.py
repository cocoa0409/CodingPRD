"""Error catalog and the ApiError exception type.

Each error carries an error_id (machine-readable), an http_status, and a
human-readable message. The error_id and http codes are taken verbatim from
the PRD §5 / SCAFFOLD §1.6 error catalog.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id constants (from PRD §5 / scaffold §1.6).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_ASSIGNED_INSPECTOR = "ERR_NOT_ASSIGNED_INSPECTOR"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_INSPECTOR_NOT_CERTIFIED = "ERR_INSPECTOR_NOT_CERTIFIED"
ERR_TERRITORY_MISMATCH = "ERR_TERRITORY_MISMATCH"
ERR_INSPECTOR_DOUBLE_BOOKED = "ERR_INSPECTOR_DOUBLE_BOOKED"
ERR_PROPERTY_SAME_DAY_CONFLICT = "ERR_PROPERTY_SAME_DAY_CONFLICT"
ERR_DAILY_CAPACITY_EXCEEDED = "ERR_DAILY_CAPACITY_EXCEEDED"
ERR_DUPLICATE_ADDON = "ERR_DUPLICATE_ADDON"
ERR_REINSPECTION_NOT_WARRANTED = "ERR_REINSPECTION_NOT_WARRANTED"
ERR_REINSPECTION_TOO_SOON = "ERR_REINSPECTION_TOO_SOON"
ERR_ORDER_UNPAID = "ERR_ORDER_UNPAID"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_VALIDATION_RANGE = "ERR_VALIDATION_RANGE"


# Convenience constructors.
def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role is not permitted to call this endpoint."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_assigned_inspector(msg="Acting inspector is not the order's assigned inspector."):
    return ApiError(ERR_NOT_ASSIGNED_INSPECTOR, 403, msg)


def not_found(msg="Resource not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request payload."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Resource is not in a valid state for this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def validation_range(msg="Query parameter out of bounds."):
    return ApiError(ERR_VALIDATION_RANGE, 400, msg)

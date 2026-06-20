"""Error classes and error-id constants for the Hospital Bed Flow API."""


class ApiError(Exception):
    """An error carrying a stable error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / structural
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                    # 404 (path)
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"  # 404 (body FK)
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"        # 422
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"  # 422

# State / business
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
ERR_ISOLATION_REQUIRED = "ERR_ISOLATION_REQUIRED"  # 409
ERR_TELEMETRY_REQUIRED = "ERR_TELEMETRY_REQUIRED"  # 409
ERR_COHORT_CONFLICT = "ERR_COHORT_CONFLICT"        # 409
ERR_BED_NOT_AVAILABLE = "ERR_BED_NOT_AVAILABLE"    # 409
ERR_SAME_BED = "ERR_SAME_BED"                      # 409
ERR_OPEN_BARRIERS = "ERR_OPEN_BARRIERS"            # 409
ERR_NO_ELIGIBLE_BED = "ERR_NO_ELIGIBLE_BED"        # 409
ERR_BED_NOT_DIRTY = "ERR_BED_NOT_DIRTY"            # 409
ERR_EVS_TASK_EXISTS = "ERR_EVS_TASK_EXISTS"        # 409
ERR_BED_OCCUPIED = "ERR_BED_OCCUPIED"              # 409

# Concurrency
ERR_STALE_BED_VERSION = "ERR_STALE_BED_VERSION"    # 412


_HTTP = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN: 403,
    ERR_NOT_FOUND: 404,
    ERR_REFERENCE_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 422,
    ERR_INVALID_PAGINATION: 422,
    ERR_INVALID_STATE: 409,
    ERR_ISOLATION_REQUIRED: 409,
    ERR_TELEMETRY_REQUIRED: 409,
    ERR_COHORT_CONFLICT: 409,
    ERR_BED_NOT_AVAILABLE: 409,
    ERR_SAME_BED: 409,
    ERR_OPEN_BARRIERS: 409,
    ERR_NO_ELIGIBLE_BED: 409,
    ERR_BED_NOT_DIRTY: 409,
    ERR_EVS_TASK_EXISTS: 409,
    ERR_BED_OCCUPIED: 409,
    ERR_STALE_BED_VERSION: 412,
}


def err(error_id, message=None):
    """Construct an ApiError with the canonical HTTP status for the id."""
    return ApiError(error_id, _HTTP[error_id], message)

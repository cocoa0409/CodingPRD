"""Error classes and error-id constants.

Every error_id and its HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries error_id, message, http_status for the standard error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_HEIGHT_REQUIREMENT_NOT_MET = "ERR_HEIGHT_REQUIREMENT_NOT_MET"  # 422
ERR_ACCESSIBILITY_BLOCKED = "ERR_ACCESSIBILITY_BLOCKED"           # 422
ERR_WINDOW_NOT_REDEEMABLE = "ERR_WINDOW_NOT_REDEEMABLE"           # 422
ERR_PEAK_GATE_BLOCKED = "ERR_PEAK_GATE_BLOCKED"       # 422
ERR_VQ_LIMIT_REACHED = "ERR_VQ_LIMIT_REACHED"         # 422
ERR_HOLD_LIMIT_REACHED = "ERR_HOLD_LIMIT_REACHED"     # 422
ERR_WINDOW_EXHAUSTED = "ERR_WINDOW_EXHAUSTED"         # 409
ERR_PARK_AT_CAPACITY = "ERR_PARK_AT_CAPACITY"         # 409
ERR_NO_REPLACEMENT_WINDOW = "ERR_NO_REPLACEMENT_WINDOW"  # 409
ERR_VALIDATION = "ERR_VALIDATION"                     # 400
ERR_LEADER_REMOVAL_FORBIDDEN = "ERR_LEADER_REMOVAL_FORBIDDEN"  # 409
ERR_GUEST_PARK_MISMATCH = "ERR_GUEST_PARK_MISMATCH"   # 422


_HTTP = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_NOT_RESOURCE_OWNER: 403,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_STALE_VERSION: 412,
    ERR_HEIGHT_REQUIREMENT_NOT_MET: 422,
    ERR_ACCESSIBILITY_BLOCKED: 422,
    ERR_WINDOW_NOT_REDEEMABLE: 422,
    ERR_PEAK_GATE_BLOCKED: 422,
    ERR_VQ_LIMIT_REACHED: 422,
    ERR_HOLD_LIMIT_REACHED: 422,
    ERR_WINDOW_EXHAUSTED: 409,
    ERR_PARK_AT_CAPACITY: 409,
    ERR_NO_REPLACEMENT_WINDOW: 409,
    ERR_VALIDATION: 400,
    ERR_LEADER_REMOVAL_FORBIDDEN: 409,
    ERR_GUEST_PARK_MISMATCH: 422,
}


def err(error_id, message=None):
    """Raise an ApiError using the catalog's HTTP status for error_id."""
    raise ApiError(error_id, _HTTP[error_id], message)

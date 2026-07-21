"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id constants (from SCAFFOLD §1.6 / PRD §5)
ERR_MISSING_USER_CONTEXT = "ERR_MISSING_USER_CONTEXT"       # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"           # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                             # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                 # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                     # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                     # 412
ERR_SELF_APPROVAL = "ERR_SELF_APPROVAL"                     # 403
ERR_TRAVELER_SUSPENDED = "ERR_TRAVELER_SUSPENDED"           # 409
ERR_ADVANCE_PURCHASE_VIOLATION = "ERR_ADVANCE_PURCHASE_VIOLATION"  # 409
ERR_TRAVELER_DOUBLE_BOOKED = "ERR_TRAVELER_DOUBLE_BOOKED"   # 409
ERR_RATE_UNAVAILABLE = "ERR_RATE_UNAVAILABLE"               # 409
ERR_CREDIT_UNAVAILABLE = "ERR_CREDIT_UNAVAILABLE"           # 409
ERR_POLICY_VIOLATION = "ERR_POLICY_VIOLATION"               # 409
ERR_VENDOR_CAPACITY_EXCEEDED = "ERR_VENDOR_CAPACITY_EXCEEDED"  # 409
ERR_APPROVAL_REQUIRED = "ERR_APPROVAL_REQUIRED"            # 409
ERR_APPROVAL_RANK_TOO_LOW = "ERR_APPROVAL_RANK_TOO_LOW"    # 409


def bad_request(message="Malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def not_found(message="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, message)


def invalid_state(message="Resource is not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, message)

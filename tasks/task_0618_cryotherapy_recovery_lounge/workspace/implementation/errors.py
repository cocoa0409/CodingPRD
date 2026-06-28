"""Error classes and error-id constants (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    """An application error carrying the scaffold's error_id, message, HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / scaffold §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"   # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_CONTRAINDICATION_BLOCK = "ERR_CONTRAINDICATION_BLOCK"  # 422
ERR_WAIVER_REQUIRED = "ERR_WAIVER_REQUIRED"           # 422
ERR_ROOM_UNAVAILABLE = "ERR_ROOM_UNAVAILABLE"         # 409
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"               # 409
ERR_NO_TECHNICIAN_ON_DUTY = "ERR_NO_TECHNICIAN_ON_DUTY"  # 409
ERR_INTRO_ALREADY_USED = "ERR_INTRO_ALREADY_USED"     # 409
ERR_NOT_AN_UPGRADE = "ERR_NOT_AN_UPGRADE"             # 409
ERR_INSUFFICIENT_CREDITS = "ERR_INSUFFICIENT_CREDITS"  # 422
ERR_LOCATION_CLOSED = "ERR_LOCATION_CLOSED"           # 409
ERR_SERVICE_INACTIVE = "ERR_SERVICE_INACTIVE"         # 409
ERR_FREEZE_CYCLES_INVALID = "ERR_FREEZE_CYCLES_INVALID"  # 400
ERR_VALIDATION_PAGINATION = "ERR_VALIDATION_PAGINATION"  # 400
ERR_DUPLICATE_SUBSCRIPTION = "ERR_DUPLICATE_SUBSCRIPTION"  # 409


# Convenience constructors that pin the HTTP status from the catalog.
def unauthenticated(msg="Missing or unrecognized authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="A referenced resource does not exist"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def stale_version(msg="The supplied expected version is stale"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Resource is not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def pagination(msg="limit or offset out of allowed bounds"):
    return ApiError(ERR_VALIDATION_PAGINATION, 400, msg)


def freeze_cycles_invalid(msg="freeze_cycles must be an integer in [1, 3]"):
    return ApiError(ERR_FREEZE_CYCLES_INVALID, 400, msg)

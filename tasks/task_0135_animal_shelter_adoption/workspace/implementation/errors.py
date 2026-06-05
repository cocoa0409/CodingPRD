"""Error classes and error-id constants from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status for the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authorization
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
# Existence / shape
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"        # 422
# State / business
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_CHIP_MISMATCH = "ERR_CHIP_MISMATCH"              # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 409
ERR_STRAY_HOLD_ACTIVE = "ERR_STRAY_HOLD_ACTIVE"      # 409
ERR_NOT_MEDICALLY_CLEARED = "ERR_NOT_MEDICALLY_CLEARED"  # 409
ERR_KENNEL_OCCUPIED = "ERR_KENNEL_OCCUPIED"          # 409
ERR_FOSTER_HOME_FULL = "ERR_FOSTER_HOME_FULL"        # 409
ERR_FOSTER_COOLDOWN = "ERR_FOSTER_COOLDOWN"          # 409
ERR_APPLICATION_CONFLICT = "ERR_APPLICATION_CONFLICT"    # 409
ERR_DUPLICATE_CHIP = "ERR_DUPLICATE_CHIP"            # 409
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"          # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412


def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Caller role is not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def validation_limit(msg="Pagination limit/offset out of range"):
    return ApiError(ERR_VALIDATION_LIMIT, 422, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)

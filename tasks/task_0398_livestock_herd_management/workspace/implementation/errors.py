"""Error classes and error-id constants.

Every error_id and HTTP status here is taken verbatim from the PRD §5 error
catalogue and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Foundational (priority 1..5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409

# Domain
ERR_INVALID_PEDIGREE = "ERR_INVALID_PEDIGREE"        # 422
ERR_DUPLICATE_IDENTIFIER = "ERR_DUPLICATE_IDENTIFIER"  # 409
ERR_WITHDRAWAL_NOT_CLEARED = "ERR_WITHDRAWAL_NOT_CLEARED"  # 409
ERR_ROUTE_NOT_PERMITTED = "ERR_ROUTE_NOT_PERMITTED"  # 422
ERR_ANIMAL_ALREADY_LISTED = "ERR_ANIMAL_ALREADY_LISTED"  # 409
ERR_REST_PERIOD_VIOLATION = "ERR_REST_PERIOD_VIOLATION"  # 409
ERR_PASTURE_OVER_CAPACITY = "ERR_PASTURE_OVER_CAPACITY"  # 409
ERR_COMMISSION_NOT_ALLOWED = "ERR_COMMISSION_NOT_ALLOWED"  # 422
ERR_WEIGH_DATE_INVALID = "ERR_WEIGH_DATE_INVALID"    # 422
ERR_DOSE_DATES_INVALID = "ERR_DOSE_DATES_INVALID"    # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_HERD_MISMATCH = "ERR_HERD_MISMATCH"              # 409
ERR_NOT_LATEST_MOVEMENT = "ERR_NOT_LATEST_MOVEMENT"  # 409
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"        # 422
ERR_ANIMAL_NOT_ACTIVE = "ERR_ANIMAL_NOT_ACTIVE"      # 409
ERR_EMPTY_LOT = "ERR_EMPTY_LOT"                      # 409


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role not permitted for the endpoint"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Requested transition not allowed from current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def validation_limit(msg="Pagination limit out of [1,100] or offset negative"):
    return ApiError(ERR_VALIDATION_LIMIT, 422, msg)

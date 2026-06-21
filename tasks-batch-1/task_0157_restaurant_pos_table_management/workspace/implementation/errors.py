"""Error classes and error-id constants (from PRD §5 catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID constants — exact spellings from PRD §5 / scaffold §1.6
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_TABLE_VERSION = "ERR_STALE_TABLE_VERSION"  # 412
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"      # 409
ERR_ITEM_86 = "ERR_ITEM_86"                          # 409
ERR_EMPTY_COURSE = "ERR_EMPTY_COURSE"                # 409
ERR_COMP_CAP_EXCEEDED = "ERR_COMP_CAP_EXCEEDED"      # 409
ERR_UNDERPAID = "ERR_UNDERPAID"                      # 409
ERR_TABLE_DOUBLE_BOOKED = "ERR_TABLE_DOUBLE_BOOKED"  # 409
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"              # 409
ERR_INVALID_SPLIT = "ERR_INVALID_SPLIT"              # 422
ERR_POOL_EMPTY = "ERR_POOL_EMPTY"                    # 409


def unauthenticated(msg="Missing or blank authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is missing required fields or has bad values."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource is not in a valid state for this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)

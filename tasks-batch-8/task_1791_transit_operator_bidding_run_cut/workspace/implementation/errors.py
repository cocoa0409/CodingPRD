"""Error classes and error ID constants (from SCAFFOLD error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"              # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                          # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                          # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"      # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                  # 409
ERR_INVALID_RUN_PIECES = "ERR_INVALID_RUN_PIECES"        # 422
ERR_DUPLICATE_RUN_NUMBER = "ERR_DUPLICATE_RUN_NUMBER"    # 409
ERR_DUPLICATE_PREFERENCE = "ERR_DUPLICATE_PREFERENCE"    # 409
ERR_DATE_OUT_OF_RANGE = "ERR_DATE_OUT_OF_RANGE"          # 422
ERR_RUN_NOT_BIDDABLE = "ERR_RUN_NOT_BIDDABLE"            # 422
ERR_SPREAD_LIMIT_EXCEEDED = "ERR_SPREAD_LIMIT_EXCEEDED"  # 422
ERR_INVALID_ACTUAL_MINUTES = "ERR_INVALID_ACTUAL_MINUTES"  # 422
ERR_INSUFFICIENT_VACATION_BALANCE = "ERR_INSUFFICIENT_VACATION_BALANCE"  # 422
ERR_VACATION_SLOT_FULL = "ERR_VACATION_SLOT_FULL"        # 409
ERR_NO_COVER_AVAILABLE = "ERR_NO_COVER_AVAILABLE"        # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                  # 412
ERR_GRIEVANCE_PRECONDITION = "ERR_GRIEVANCE_PRECONDITION"  # 422
ERR_VALIDATION = "ERR_VALIDATION"                        # 400


def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Authenticated role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Path-referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def reference_not_found(msg="Body-referenced resource does not exist"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, msg, 404)


def invalid_state(msg="Target resource not in a state permitting the operation"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def validation(msg="Malformed request body"):
    return ApiError(ERR_VALIDATION, msg, 400)

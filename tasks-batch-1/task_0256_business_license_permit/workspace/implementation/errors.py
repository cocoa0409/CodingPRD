"""Error classes and error-id constants drawn from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / generic ladder
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                             # 409
ERR_VALIDATION = "ERR_VALIDATION"                                    # 422
ERR_PAGINATION_INVALID = "ERR_PAGINATION_INVALID"                    # 400

# Business rules
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"             # 403
ERR_INSPECTION_PREREQUISITE_NOT_MET = "ERR_INSPECTION_PREREQUISITE_NOT_MET"  # 409
ERR_BUSINESS_NOT_IN_GOOD_STANDING = "ERR_BUSINESS_NOT_IN_GOOD_STANDING"      # 409
ERR_LICENSE_NOT_TRANSFERABLE = "ERR_LICENSE_NOT_TRANSFERABLE"      # 409
ERR_ZONING_DENIED = "ERR_ZONING_DENIED"                            # 409
ERR_RENEWAL_WINDOW_CLOSED = "ERR_RENEWAL_WINDOW_CLOSED"            # 409
ERR_REVOCATION_THRESHOLD_NOT_REACHED = "ERR_REVOCATION_THRESHOLD_NOT_REACHED"  # 409
ERR_OUTSTANDING_FEES = "ERR_OUTSTANDING_FEES"                      # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                            # 412
ERR_DUPLICATE_ACTIVITY_CODE = "ERR_DUPLICATE_ACTIVITY_CODE"        # 409
ERR_INSPECTION_ALREADY_RECORDED = "ERR_INSPECTION_ALREADY_RECORDED"  # 409


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Missing required field, bad type, or out-of-set enum value"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Resource not in a state from which the requested transition is defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def validation(msg="Semantically invalid input"):
    return ApiError(ERR_VALIDATION, 422, msg)


def pagination_invalid(msg="limit/offset out of allowed range"):
    return ApiError(ERR_PAGINATION_INVALID, 400, msg)

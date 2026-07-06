"""Error classes and error-id constants (PRD §5 catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 error catalogue (error_id -> http status)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_LAB_OVERDUE = "ERR_LAB_OVERDUE"                  # 409
ERR_NURSE_NOT_LICENSED = "ERR_NURSE_NOT_LICENSED"    # 422
ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"              # 409
ERR_PUMP_DOUBLE_BOOKED = "ERR_PUMP_DOUBLE_BOOKED"    # 409
ERR_NURSE_DOUBLE_BOOKED = "ERR_NURSE_DOUBLE_BOOKED"  # 409
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"  # 409
ERR_AUTH_UNITS_EXCEEDED = "ERR_AUTH_UNITS_EXCEEDED"  # 422
ERR_STALE_ORDER_VERSION = "ERR_STALE_ORDER_VERSION"  # 412
ERR_THERAPY_INCOMPLETE = "ERR_THERAPY_INCOMPLETE"    # 409


def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted to invoke this endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource is not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)

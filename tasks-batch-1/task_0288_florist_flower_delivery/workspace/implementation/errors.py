"""Error classes and error ID constants (from PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"              # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_PRECONDITION_NOT_MET = "ERR_PRECONDITION_NOT_MET"  # 409
ERR_PAST_SAME_DAY_CUTOFF = "ERR_PAST_SAME_DAY_CUTOFF"  # 409
ERR_DELIVERY_DATE_IN_PAST = "ERR_DELIVERY_DATE_IN_PAST"  # 409
ERR_SUBSTITUTION_NOT_ALLOWED = "ERR_SUBSTITUTION_NOT_ALLOWED"  # 409
ERR_ZONE_WINDOW_FULL = "ERR_ZONE_WINDOW_FULL"         # 409
ERR_NO_FLORIST_AVAILABLE = "ERR_NO_FLORIST_AVAILABLE"  # 409
ERR_STALE_ORDER_VERSION = "ERR_STALE_ORDER_VERSION"    # 412
ERR_SCHEDULE_EXHAUSTED = "ERR_SCHEDULE_EXHAUSTED"      # 409
ERR_ZONE_INACTIVE = "ERR_ZONE_INACTIVE"               # 409
ERR_ARRANGEMENT_INACTIVE = "ERR_ARRANGEMENT_INACTIVE"  # 409
ERR_CLAIM_WINDOW_INVALID = "ERR_CLAIM_WINDOW_INVALID"  # 409
ERR_VALIDATION_RANGE = "ERR_VALIDATION_RANGE"          # 422


def unauthenticated(msg=None):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg=None):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg=None):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg=None):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg=None):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def validation_range(msg=None):
    return ApiError(ERR_VALIDATION_RANGE, 422, msg)


def invalid_state(msg=None):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def precondition_not_met(msg=None):
    return ApiError(ERR_PRECONDITION_NOT_MET, 409, msg)


def stale_order_version(msg=None):
    return ApiError(ERR_STALE_ORDER_VERSION, 412, msg)

"""Error classes and error-id constants (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authorization
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"              # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404

# State / business
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_MEMBERSHIP_NOT_ACTIVE = "ERR_MEMBERSHIP_NOT_ACTIVE"  # 409
ERR_CAPABILITY_MISMATCH = "ERR_CAPABILITY_MISMATCH"   # 409
ERR_PROVIDER_UNAVAILABLE = "ERR_PROVIDER_UNAVAILABLE"  # 409
ERR_OFFER_ALREADY_OUTSTANDING = "ERR_OFFER_ALREADY_OUTSTANDING"  # 409
ERR_DISPATCH_LIMIT_REACHED = "ERR_DISPATCH_LIMIT_REACHED"  # 409
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"               # 409
ERR_NO_BAY_AVAILABLE = "ERR_NO_BAY_AVAILABLE"         # 409
ERR_ANNUAL_LIMIT_EXCEEDED = "ERR_ANNUAL_LIMIT_EXCEEDED"  # 409
ERR_CALL_NOT_COMPLETED = "ERR_CALL_NOT_COMPLETED"     # 409

# Request validation
ERR_INVALID_CLAIM_TARGET = "ERR_INVALID_CLAIM_TARGET"  # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 422
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"     # 422

# OCC
ERR_STALE_CALL_VERSION = "ERR_STALE_CALL_VERSION"     # 412


def unauthenticated(msg="Missing or unknown user context."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role is not permitted to perform this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Acting user does not own the targeted resource."):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource is not in a state from which this transition is legal."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg="Request body is invalid."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_pagination(msg="Invalid pagination parameters."):
    return ApiError(ERR_INVALID_PAGINATION, 422, msg)

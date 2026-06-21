"""Error classes and error-id constants (PRD §5 error catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"             # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"             # 412
ERR_GOLF_NOT_ALLOWED = "ERR_GOLF_NOT_ALLOWED"       # 422
ERR_MEMBERSHIP_NOT_ACTIVE = "ERR_MEMBERSHIP_NOT_ACTIVE"  # 409
ERR_RESOURCE_CONFLICT = "ERR_RESOURCE_CONFLICT"     # 409
ERR_CATEGORY_AT_CAPACITY = "ERR_CATEGORY_AT_CAPACITY"  # 409
ERR_GUEST_QUOTA_EXCEEDED = "ERR_GUEST_QUOTA_EXCEEDED"  # 409
ERR_OUTSTANDING_BALANCE = "ERR_OUTSTANDING_BALANCE"  # 409
ERR_NO_ELIGIBLE_MEMBERS = "ERR_NO_ELIGIBLE_MEMBERS"  # 409
ERR_PAYMENT_INVALID = "ERR_PAYMENT_INVALID"         # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"         # 400
ERR_VALIDATION = "ERR_VALIDATION"                   # 422


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_resource_owner(msg="Member does not own this resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def golf_not_allowed(msg="Category does not allow golf"):
    return ApiError(ERR_GOLF_NOT_ALLOWED, 422, msg)


def membership_not_active(msg="Membership is not ACTIVE"):
    return ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409, msg)


def resource_conflict(msg="Requested interval conflicts with an existing reservation"):
    return ApiError(ERR_RESOURCE_CONFLICT, 409, msg)


def category_at_capacity(msg="Category is at capacity"):
    return ApiError(ERR_CATEGORY_AT_CAPACITY, 409, msg)


def guest_quota_exceeded(msg="Sponsor guest-visit quota exceeded"):
    return ApiError(ERR_GUEST_QUOTA_EXCEEDED, 409, msg)


def outstanding_balance(msg="Membership has a non-zero charge balance"):
    return ApiError(ERR_OUTSTANDING_BALANCE, 409, msg)


def no_eligible_members(msg="No eligible memberships for the levy"):
    return ApiError(ERR_NO_ELIGIBLE_MEMBERS, 409, msg)


def payment_invalid(msg="Payment amount invalid"):
    return ApiError(ERR_PAYMENT_INVALID, 422, msg)


def invalid_request(msg="Malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def validation(msg="Semantic field constraint violated"):
    return ApiError(ERR_VALIDATION, 422, msg)

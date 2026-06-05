"""Error classes and error-id constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (PRD §5 / scaffold errors)
ERR_AUTH_MISSING = "ERR_AUTH_MISSING"                       # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                   # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                             # 404
ERR_VALIDATION = "ERR_VALIDATION"                           # 422
ERR_DUPLICATE_TIER = "ERR_DUPLICATE_TIER"                   # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                     # 409
ERR_TOKEN_MISMATCH = "ERR_TOKEN_MISMATCH"                   # 409
ERR_ANTI_PASSBACK = "ERR_ANTI_PASSBACK"                     # 409
ERR_INTERCHANGE_DENIED = "ERR_INTERCHANGE_DENIED"           # 409
ERR_REFUND_INELIGIBLE = "ERR_REFUND_INELIGIBLE"             # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                     # 412
ERR_BUDDY_ALLOTMENT_EXHAUSTED = "ERR_BUDDY_ALLOTMENT_EXHAUSTED"  # 409
ERR_BUDDY_DATE_CONFLICT = "ERR_BUDDY_DATE_CONFLICT"         # 409


def auth_missing(msg="Authentication headers missing or role unknown"):
    return ApiError(ERR_AUTH_MISSING, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="A required field is missing or wrongly typed"):
    return ApiError(ERR_VALIDATION, 422, msg)


def invalid_state(msg="Entity is not in a state allowing this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)

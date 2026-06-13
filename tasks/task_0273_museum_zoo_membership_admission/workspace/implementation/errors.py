"""Error classes and error-id constants (read verbatim from scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"          # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"  # 403
# Existence
ERR_NOT_FOUND = "ERR_NOT_FOUND"                    # 404
# Body / pagination
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"        # 422
ERR_VALIDATION_PAGINATION = "ERR_VALIDATION_PAGINATION"  # 422
# Uniqueness
ERR_EMAIL_TAKEN = "ERR_EMAIL_TAKEN"                # 409
# State
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
# OCC
ERR_STALE_VERSION = "ERR_STALE_VERSION"            # 412
# Business
ERR_TICKET_ELIGIBILITY = "ERR_TICKET_ELIGIBILITY"        # 409
ERR_MEMBERSHIP_NOT_ACTIVE = "ERR_MEMBERSHIP_NOT_ACTIVE"  # 409
ERR_SLOT_WINDOW = "ERR_SLOT_WINDOW"                      # 409
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"                    # 409
ERR_EXHIBIT_BUFFER_CONFLICT = "ERR_EXHIBIT_BUFFER_CONFLICT"  # 409
ERR_NO_GUEST_PASS = "ERR_NO_GUEST_PASS"                  # 409
ERR_SLOT_CAPACITY = "ERR_SLOT_CAPACITY"                  # 409
ERR_HOUSEHOLD_FULL = "ERR_HOUSEHOLD_FULL"               # 409


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# Convenience constructors
def unauthenticated(msg="Missing or invalid X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_owner(msg="Caller does not own this resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Referenced resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is malformed"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_pagination(msg="limit/offset out of range"):
    return ApiError(ERR_VALIDATION_PAGINATION, 422, msg)


def invalid_state(msg="Resource not in a state from which this transition is defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)

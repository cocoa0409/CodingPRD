"""Error classes and error-id constants.

Every error_id / http_status pair is taken verbatim from SCAFFOLD.yaml §1.6
and PRD §5. Do not invent new error ids.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / RBAC / ownership
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"    # 403

# Existence / state
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"             # 409

# Business
ERR_FIRING_TEMP_MISMATCH = "ERR_FIRING_TEMP_MISMATCH"  # 409
ERR_VISIT_NOT_OPEN = "ERR_VISIT_NOT_OPEN"              # 409
ERR_PIECES_NOT_READY = "ERR_PIECES_NOT_READY"          # 409
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"      # 409
ERR_KILN_AT_CAPACITY = "ERR_KILN_AT_CAPACITY"          # 409
ERR_SERIES_FULL = "ERR_SERIES_FULL"                    # 409
ERR_DUPLICATE_ENROLLMENT = "ERR_DUPLICATE_ENROLLMENT"  # 409
ERR_ENROLLMENT_CLOSED = "ERR_ENROLLMENT_CLOSED"        # 409
ERR_MEMBER_SUSPENDED = "ERR_MEMBER_SUSPENDED"          # 409
ERR_STALE_BATCH_VERSION = "ERR_STALE_BATCH_VERSION"    # 412
ERR_BOOKING_DATE_PAST = "ERR_BOOKING_DATE_PAST"        # 422
ERR_DEPOSIT_AMOUNT_MISMATCH = "ERR_DEPOSIT_AMOUNT_MISMATCH"  # 422
ERR_INSUFFICIENT_POINTS = "ERR_INSUFFICIENT_POINTS"    # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400


# Convenience constructors -----------------------------------------------------

def unauthenticated(msg="Missing or unknown X-User-Role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="LoyaltyMember acting on a resource that is not their own"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Referenced resource id does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource not in a state permitting the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)

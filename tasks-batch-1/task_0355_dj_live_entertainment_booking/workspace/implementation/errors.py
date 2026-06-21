"""Error classes and error ID constants.

Error IDs and HTTP statuses are taken verbatim from the scaffold §1.6 error
catalog and PRD §5.
"""


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

# Existence
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                  # 404
ERR_REFERENCED_ENTITY_NOT_FOUND = "ERR_REFERENCED_ENTITY_NOT_FOUND"  # 404

# Request well-formedness
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 422

# Business
ERR_PACKAGE_RETIRED = "ERR_PACKAGE_RETIRED"           # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_BOOKING_VERSION = "ERR_STALE_BOOKING_VERSION"  # 412
ERR_EVENT_IN_PAST = "ERR_EVENT_IN_PAST"               # 422
ERR_PERFORMER_BLACKED_OUT = "ERR_PERFORMER_BLACKED_OUT"  # 409
ERR_PERFORMER_DOUBLE_BOOKED = "ERR_PERFORMER_DOUBLE_BOOKED"  # 409
ERR_BLACKOUT_OVERLAP = "ERR_BLACKOUT_OVERLAP"         # 409
ERR_SET_TOO_SHORT = "ERR_SET_TOO_SHORT"               # 422
ERR_NOT_LOWEST_RANK_BACKUP = "ERR_NOT_LOWEST_RANK_BACKUP"  # 409
ERR_NO_ELIGIBLE_BACKUP = "ERR_NO_ELIGIBLE_BACKUP"     # 409
ERR_BACKUP_IS_PRIMARY = "ERR_BACKUP_IS_PRIMARY"       # 409
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                   # 409
ERR_BALANCE_OUTSTANDING = "ERR_BALANCE_OUTSTANDING"   # 409
ERR_PAYMENT_NOT_VOIDABLE = "ERR_PAYMENT_NOT_VOIDABLE"  # 409
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"         # 422


def unauthenticated(msg="Missing or unknown authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Caller is not the owner of the targeted resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def referenced_not_found(msg="A referenced entity does not exist"):
    return ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Requested transition is not legal from current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_booking_version does not match current version"):
    return ApiError(ERR_STALE_BOOKING_VERSION, 412, msg)


def validation_limit(msg="Pagination limit/offset out of bounds"):
    return ApiError(ERR_VALIDATION_LIMIT, 422, msg)

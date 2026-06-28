"""Error catalog (scaffold 1.6 / PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Exact error_id strings from the scaffold / PRD error catalog.
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_WAIVER_REQUIRED = "ERR_WAIVER_REQUIRED"           # 422
ERR_CERT_PREREQUISITE_NOT_MET = "ERR_CERT_PREREQUISITE_NOT_MET"  # 422
ERR_INSTRUCTOR_CONFLICT = "ERR_INSTRUCTOR_CONFLICT"   # 409
ERR_BOAT_CONFLICT = "ERR_BOAT_CONFLICT"               # 409
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"       # 409
ERR_DUPLICATE_BOOKING = "ERR_DUPLICATE_BOOKING"       # 409


def unauthenticated(msg=None):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg or "Missing or unknown authentication headers")


def forbidden(msg=None):
    return ApiError(ERR_FORBIDDEN, 403, msg or "Role not permitted for this operation")


def not_found(msg=None):
    return ApiError(ERR_NOT_FOUND, 404, msg or "Referenced resource does not exist")


def invalid_request(msg=None):
    return ApiError(ERR_INVALID_REQUEST, 400, msg or "Malformed request body")


def invalid_state(msg=None):
    return ApiError(ERR_INVALID_STATE, 409, msg or "Resource not in a valid state for this transition")


def stale_version(msg=None):
    return ApiError(ERR_STALE_VERSION, 412, msg or "Expected version does not match current version")


def waiver_required(msg=None):
    return ApiError(ERR_WAIVER_REQUIRED, 422, msg or "Active waiver with medical clearance required")


def cert_prerequisite(msg=None):
    return ApiError(ERR_CERT_PREREQUISITE_NOT_MET, 422, msg or "Certification prerequisite not met")


def instructor_conflict(msg=None):
    return ApiError(ERR_INSTRUCTOR_CONFLICT, 409, msg or "Instructor scheduling conflict")


def boat_conflict(msg=None):
    return ApiError(ERR_BOAT_CONFLICT, 409, msg or "Boat scheduling conflict")


def capacity_exceeded(msg=None):
    return ApiError(ERR_CAPACITY_EXCEEDED, 409, msg or "Capacity exceeded")


def duplicate_booking(msg=None):
    return ApiError(ERR_DUPLICATE_BOOKING, 409, msg or "Duplicate booking")

"""Error classes and error ID constants (from SCAFFOLD Table 1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / generic
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                       # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412

# Business
ERR_DOCUMENT_EXPIRED = "ERR_DOCUMENT_EXPIRED"        # 409
ERR_PREREQ_NOT_MET = "ERR_PREREQ_NOT_MET"            # 409
ERR_EXAMINER_CONFLICT = "ERR_EXAMINER_CONFLICT"      # 409
ERR_EXAMINER_NOT_CERTIFIED = "ERR_EXAMINER_NOT_CERTIFIED"  # 409
ERR_TRUCK_CLASS_MISMATCH = "ERR_TRUCK_CLASS_MISMATCH"      # 409
ERR_TRUCK_DOUBLE_BOOKED = "ERR_TRUCK_DOUBLE_BOOKED"        # 409
ERR_INSTRUCTOR_DOUBLE_BOOKED = "ERR_INSTRUCTOR_DOUBLE_BOOKED"  # 409
ERR_ENROLLMENT_NOT_TRAINING = "ERR_ENROLLMENT_NOT_TRAINING"    # 409
ERR_SESSION_NOT_ELAPSED = "ERR_SESSION_NOT_ELAPSED"  # 409
ERR_SESSION_LOCKED = "ERR_SESSION_LOCKED"            # 409
ERR_ENROLLMENT_NOT_TEST_READY = "ERR_ENROLLMENT_NOT_TEST_READY"  # 409
ERR_SPONSORSHIP_CONFLICT = "ERR_SPONSORSHIP_CONFLICT"  # 409
ERR_ENROLLMENT_NOT_PASSED = "ERR_ENROLLMENT_NOT_PASSED"  # 409


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Invalid state for requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)

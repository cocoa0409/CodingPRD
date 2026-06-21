"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / generic
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_DUPLICATE = "ERR_DUPLICATE"                      # 409

# Domain-specific
ERR_RECURRENCE_CONFIG_INVALID = "ERR_RECURRENCE_CONFIG_INVALID"        # 409
ERR_PREREQUISITE_NOT_PUBLISHED = "ERR_PREREQUISITE_NOT_PUBLISHED"      # 409
ERR_COURSE_HAS_OPEN_ENROLLMENTS = "ERR_COURSE_HAS_OPEN_ENROLLMENTS"    # 409
ERR_PATH_EMPTY = "ERR_PATH_EMPTY"                                      # 409
ERR_PATH_STEP_COURSE_NOT_PUBLISHED = "ERR_PATH_STEP_COURSE_NOT_PUBLISHED"  # 409
ERR_PATH_SEQUENCE_INVALID = "ERR_PATH_SEQUENCE_INVALID"                # 409
ERR_PATH_HAS_OPEN_ENROLLMENTS = "ERR_PATH_HAS_OPEN_ENROLLMENTS"        # 409
ERR_COURSE_NOT_PUBLISHED = "ERR_COURSE_NOT_PUBLISHED"                  # 409
ERR_PREREQUISITE_NOT_MET = "ERR_PREREQUISITE_NOT_MET"                  # 409
ERR_PATH_STEP_LOCKED = "ERR_PATH_STEP_LOCKED"                          # 409
ERR_ATTEMPTS_EXHAUSTED = "ERR_ATTEMPTS_EXHAUSTED"                      # 409
ERR_SESSION_ALREADY_OPEN = "ERR_SESSION_ALREADY_OPEN"                  # 409
ERR_ASSIGNMENT_RULE_OVERLAP = "ERR_ASSIGNMENT_RULE_OVERLAP"           # 409
ERR_PREREQUISITE_CYCLE = "ERR_PREREQUISITE_CYCLE"                      # 409


# Convenience constructors -------------------------------------------------

def unauthenticated(msg="Authentication required"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Not permitted"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Invalid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Stale version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def duplicate(msg="Duplicate resource"):
    return ApiError(ERR_DUPLICATE, 409, msg)

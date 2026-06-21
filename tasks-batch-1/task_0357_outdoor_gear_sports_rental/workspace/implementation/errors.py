"""Error catalog. error_id / http_status pairs taken verbatim from PRD §5
and SCAFFOLD §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_VALIDATION = "ERR_VALIDATION"                    # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_UNIT_NOT_AVAILABLE = "ERR_UNIT_NOT_AVAILABLE"    # 409
ERR_WINDOW_CONFLICT = "ERR_WINDOW_CONFLICT"          # 409
ERR_SLOT_FULL = "ERR_SLOT_FULL"                      # 409
ERR_LESSON_REQUIRED = "ERR_LESSON_REQUIRED"          # 422
ERR_CUSTOMER_SUSPENDED = "ERR_CUSTOMER_SUSPENDED"    # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_ASSESSMENT_DISPUTED = "ERR_ASSESSMENT_DISPUTED"  # 409


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="Malformed request"):
    return ApiError(ERR_VALIDATION, 400, msg)


def invalid_state(msg="Resource not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def unit_not_available(msg="Gear unit not available, inactive type/rate card, or category mismatch"):
    return ApiError(ERR_UNIT_NOT_AVAILABLE, 409, msg)


def window_conflict(msg="Requested window overlaps an existing window on the unit"):
    return ApiError(ERR_WINDOW_CONFLICT, 409, msg)


def slot_full(msg="Lesson slot at capacity"):
    return ApiError(ERR_SLOT_FULL, 409, msg)


def lesson_required(msg="Beginner on a lesson-required gear type must attach a LESSON add-on"):
    return ApiError(ERR_LESSON_REQUIRED, 422, msg)


def customer_suspended(msg="Customer standing is SUSPENDED"):
    return ApiError(ERR_CUSTOMER_SUSPENDED, 409, msg)


def stale_version(msg="OCC version mismatch"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def assessment_disputed(msg="Cannot settle while the damage assessment is DISPUTED"):
    return ApiError(ERR_ASSESSMENT_DISPUTED, 409, msg)

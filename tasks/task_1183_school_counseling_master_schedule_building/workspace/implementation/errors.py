"""Error catalog: ApiError exception + error id constants (SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error IDs ---------------------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_INVALID_TERM_POSTURE = "ERR_INVALID_TERM_POSTURE"  # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_FORBIDDEN_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"    # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_NO_SHOW_FREEZE = "ERR_NO_SHOW_FREEZE"              # 422
ERR_COURSE_INELIGIBLE = "ERR_COURSE_INELIGIBLE"        # 422
ERR_REQUEST_CAP_EXCEEDED = "ERR_REQUEST_CAP_EXCEEDED"  # 422
ERR_SECTION_ASSIGNMENT_INVALID = "ERR_SECTION_ASSIGNMENT_INVALID"  # 422
ERR_GRID_CONFLICT = "ERR_GRID_CONFLICT"                # 409
ERR_APPOINTMENT_CONFLICT = "ERR_APPOINTMENT_CONFLICT"  # 409
ERR_STUDENT_PERIOD_CONFLICT = "ERR_STUDENT_PERIOD_CONFLICT"  # 409
ERR_SECTION_FULL = "ERR_SECTION_FULL"                  # 422
ERR_CREDIT_CEILING_EXCEEDED = "ERR_CREDIT_CEILING_EXCEEDED"  # 422
ERR_SINGLETON_CAP_EXCEEDED = "ERR_SINGLETON_CAP_EXCEEDED"  # 422
ERR_CHANGE_QUOTA_EXCEEDED = "ERR_CHANGE_QUOTA_EXCEEDED"  # 422
ERR_COHORT_CAP_EXCEEDED = "ERR_COHORT_CAP_EXCEEDED"    # 422
ERR_CASELOAD_FULL = "ERR_CASELOAD_FULL"                # 422
ERR_NO_ELIGIBLE_SECTION = "ERR_NO_ELIGIBLE_SECTION"    # 422
ERR_RECOVERY_NO_SECTION = "ERR_RECOVERY_NO_SECTION"    # 422
ERR_STALE_TERM_VERSION = "ERR_STALE_TERM_VERSION"      # 412
ERR_PUBLISH_BLOCKED = "ERR_PUBLISH_BLOCKED"            # 409
ERR_CLOSE_WINDOW_BLOCKED = "ERR_CLOSE_WINDOW_BLOCKED"  # 409


def not_found(msg="Resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_posture(msg="Term posture does not permit this operation"):
    return ApiError(ERR_INVALID_TERM_POSTURE, 409, msg)


def invalid_state(msg="Entity is not in a legal state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def forbidden_ownership(msg="Acting user does not own the target resource"):
    return ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, msg)

"""Error classes and error-id constants.

All error_id strings and their HTTP statuses are taken verbatim from
PRD §5 (Error Code Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- error catalogue (error_id -> http status) ---------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_COHORT_TIMING = "ERR_COHORT_TIMING"              # 409
ERR_COHORT_FULL = "ERR_COHORT_FULL"                  # 409
ERR_COOLING_OFF_EXPIRED = "ERR_COOLING_OFF_EXPIRED"  # 409
ERR_DEPOSIT_ALREADY_RESOLVED = "ERR_DEPOSIT_ALREADY_RESOLVED"  # 409
ERR_DISMISSAL_NOT_JUSTIFIED = "ERR_DISMISSAL_NOT_JUSTIFIED"    # 409
ERR_PROGRESS_INCOMPLETE = "ERR_PROGRESS_INCOMPLETE"  # 409
ERR_DEFERMENT_INELIGIBLE = "ERR_DEFERMENT_INELIGIBLE"          # 409
ERR_DEFERMENT_OVERLAP = "ERR_DEFERMENT_OVERLAP"      # 409
ERR_INCOME_PERIOD_OVERLAP = "ERR_INCOME_PERIOD_OVERLAP"        # 409
ERR_SALARY_REQUIRED = "ERR_SALARY_REQUIRED"          # 400
ERR_OUTCOME_NOT_GRADUATE = "ERR_OUTCOME_NOT_GRADUATE"          # 409
ERR_VALIDATION = "ERR_VALIDATION"                    # 422


def unauthenticated(msg="Missing or unrecognized role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_enrollment_version does not match current Enrollment.version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def validation(msg="Pagination/query parameter out of bounds"):
    return ApiError(ERR_VALIDATION, 422, msg)

"""Error classes and error ID constants (from SCAFFOLD errors catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_INVALID_PARTICIPANT_DATA = "ERR_INVALID_PARTICIPANT_DATA"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_PLAN_TERMINATED = "ERR_PLAN_TERMINATED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_ACTUARY_NOT_ENROLLED = "ERR_ACTUARY_NOT_ENROLLED"
ERR_FILING_DEADLINE_PASSED = "ERR_FILING_DEADLINE_PASSED"
ERR_REVOCATION_WINDOW_EXPIRED = "ERR_REVOCATION_WINDOW_EXPIRED"
ERR_ELECTION_WINDOW_CONFLICT = "ERR_ELECTION_WINDOW_CONFLICT"
ERR_PLAN_YEAR_MISMATCH = "ERR_PLAN_YEAR_MISMATCH"
ERR_ASSUMPTION_MISMATCH = "ERR_ASSUMPTION_MISMATCH"
ERR_REFERENCE_NOT_LOCKED = "ERR_REFERENCE_NOT_LOCKED"
ERR_VALUATION_RUN_NOT_CERTIFIED = "ERR_VALUATION_RUN_NOT_CERTIFIED"
ERR_CENSUS_YEAR_CONFLICT = "ERR_CENSUS_YEAR_CONFLICT"
ERR_ASSUMPTION_YEAR_CONFLICT = "ERR_ASSUMPTION_YEAR_CONFLICT"
ERR_UNIQUENESS_VIOLATION = "ERR_UNIQUENESS_VIOLATION"
ERR_NO_AMENDMENT_DELTA = "ERR_NO_AMENDMENT_DELTA"
ERR_CREDIT_BALANCE_EXCEEDED = "ERR_CREDIT_BALANCE_EXCEEDED"
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"
ERR_STALE_VERSION = "ERR_STALE_VERSION"


def unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="Malformed request body"):
    return ApiError(ERR_VALIDATION, 400, msg)


def invalid_state(msg="Entity is not in a valid state for this operation"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def plan_terminated(msg="Plan is TERMINATED"):
    return ApiError(ERR_PLAN_TERMINATED, 409, msg)


def stale_version(msg="expected_plan_version does not match the plan's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)

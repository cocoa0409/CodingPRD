"""Error classes and error ID constants.

Every error_id and HTTP status traces to PRD §5 Error Code Catalogue and
SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries the scaffold-defined error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalogue — (error_id, http_status). Defaults messages are filled in
# at raise sites; helpers below supply sensible defaults.
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_CLASSROOM_VERSION = "ERR_STALE_CLASSROOM_VERSION"
ERR_TIER_LEVEL_MISMATCH = "ERR_TIER_LEVEL_MISMATCH"
ERR_AGE_OUT_OF_RANGE = "ERR_AGE_OUT_OF_RANGE"
ERR_CLASSROOM_NOT_COMPLIANT = "ERR_CLASSROOM_NOT_COMPLIANT"
ERR_CLASSROOM_FULL = "ERR_CLASSROOM_FULL"
ERR_GUIDE_DOUBLE_BOOKED = "ERR_GUIDE_DOUBLE_BOOKED"
ERR_OBSERVATION_OVERLAP = "ERR_OBSERVATION_OVERLAP"
ERR_INVALID_INTERVAL = "ERR_INVALID_INTERVAL"
ERR_DEPOSIT_AMOUNT_MISMATCH = "ERR_DEPOSIT_AMOUNT_MISMATCH"
ERR_REFUND_NOT_ELIGIBLE = "ERR_REFUND_NOT_ELIGIBLE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


def unauthenticated(message="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, message)


def forbidden_role(message="Acting role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, message)


def not_resource_owner(message="Acting parent does not own the resource."):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, message)


def not_found(message="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, message)


def invalid_state(message="Requested transition not defined from current state."):
    return ApiError(ERR_INVALID_STATE, 409, message)


def stale_classroom_version(message="expected_classroom_version does not match current classroom version."):
    return ApiError(ERR_STALE_CLASSROOM_VERSION, 412, message)


def tier_level_mismatch(message="Classroom level does not match tier level, or tier is inactive."):
    return ApiError(ERR_TIER_LEVEL_MISMATCH, 422, message)


def age_out_of_range(message="Student age in months outside the classroom band."):
    return ApiError(ERR_AGE_OUT_OF_RANGE, 422, message)


def classroom_not_compliant(message="Classroom is not COMPLIANT."):
    return ApiError(ERR_CLASSROOM_NOT_COMPLIANT, 409, message)


def classroom_full(message="Classroom is at capacity."):
    return ApiError(ERR_CLASSROOM_FULL, 409, message)


def guide_double_booked(message="Booking overlaps another booked slot for the same guide."):
    return ApiError(ERR_GUIDE_DOUBLE_BOOKED, 409, message)


def observation_overlap(message="Observation window overlaps another window for the same classroom."):
    return ApiError(ERR_OBSERVATION_OVERLAP, 409, message)


def invalid_interval(message="Interval end is not strictly after start."):
    return ApiError(ERR_INVALID_INTERVAL, 422, message)


def deposit_amount_mismatch(message="Deposit payment amount or timing is invalid."):
    return ApiError(ERR_DEPOSIT_AMOUNT_MISMATCH, 422, message)


def refund_not_eligible(message="Enrollment not WITHDRAWN or a non-VOID refund request already exists."):
    return ApiError(ERR_REFUND_NOT_ELIGIBLE, 409, message)


def invalid_request(message="Malformed or invalid request."):
    return ApiError(ERR_INVALID_REQUEST, 400, message)

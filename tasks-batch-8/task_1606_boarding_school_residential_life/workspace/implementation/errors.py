"""Error catalog: error ids, HTTP statuses, and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Catalog (id -> http status) -------------------------------------------
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_MISSING_REQUIRED_FIELD": 400,
    "ERR_INVALID_FIELD_VALUE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_TERM_NOT_ACTIVE": 409,
    "ERR_STUDENT_NOT_ENROLLED": 409,
    "ERR_DORM_CLOSED": 409,
    "ERR_ORDER_NOT_ACTIVE": 409,
    "ERR_MEDICATION_ON_HOLD": 422,
    "ERR_WITNESS_REQUIRED": 422,
    "ERR_GUARDIAN_NOT_APPROVED": 422,
    "ERR_DOSE_ALREADY_LOGGED": 409,
    "ERR_CHECK_ALREADY_RECORDED": 409,
    "ERR_DUPLICATE_ACTIVE_ORDER": 409,
    "ERR_DUPLICATE_BREAK_REQUEST": 409,
    "ERR_SELF_ROOMMATE": 422,
    "ERR_ROOMMATE_NOT_IN_ROOM": 422,
    "ERR_ACTIVE_ASSIGNMENT_EXISTS": 409,
    "ERR_ACTIVE_TERM_EXISTS": 409,
    "ERR_DORM_GENDER_MISMATCH": 422,
    "ERR_GUARDIAN_REQUIRED": 422,
    "ERR_REPORTER_CANNOT_ADJUDICATE": 422,
    "ERR_HEARING_REQUIRED": 422,
    "ERR_APPEAL_LIMIT_REACHED": 422,
    "ERR_NOT_ELIGIBLE_BREAK_HOUSING": 422,
    "ERR_NOT_RESIDENT": 422,
    "ERR_NO_CONFIRMED_RESIDENCY": 409,
    "ERR_CHECKS_OUTSTANDING": 409,
    "ERR_SWAP_TARGET_INELIGIBLE": 422,
    "ERR_ROOM_OCCUPIED": 409,
    "ERR_LEAVE_WINDOW_OVERLAP": 409,
    "ERR_LEAVE_IN_PAST": 422,
    "ERR_HEARING_IN_PAST": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_SIGN_OUT_WINDOW": 422,
    "ERR_SHIFT_CONFLICT": 409,
    "ERR_BREAK_NOT_ACTIVE": 409,
    "ERR_LEAVE_ALLOWANCE_EXHAUSTED": 422,
    "ERR_ROOM_FULL": 422,
    "ERR_GUARDIAN_AT_CAPACITY": 422,
    "ERR_STORAGE_CAPACITY_EXCEEDED": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_STUDENT_SUSPENDED": 409,
}


def err(error_id, message):
    return ApiError(error_id, ERR[error_id], message)

"""Error catalog: error_id -> HTTP status (PRD §5 / scaffold §1.6)."""


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_PROGRAM_NOT_CLOSED": 409,
    "ERR_PROGRAM_ALREADY_SETTLED": 409,
    "ERR_PROGRAM_HAS_OPEN_AWARDS": 409,
    "ERR_AWARD_NOT_CONFIRMABLE": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_HRA_ALREADY_COMPLETED": 409,
    "ERR_EVENT_OUTSIDE_WINDOW": 422,
    "ERR_SLOT_OUTSIDE_WINDOW": 422,
    "ERR_PROGRAM_WINDOW_OVERLAP": 409,
    "ERR_CHALLENGE_WINDOW_OVERLAP": 409,
    "ERR_KIOSK_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_EVENT": 409,
    "ERR_PARTICIPATION_EXISTS": 409,
    "ERR_CHALLENGE_PROGRAM_MISMATCH": 422,
    "ERR_REFERRAL_SESSIONS_INSUFFICIENT": 409,
    "ERR_COHORT_TOO_SMALL": 422,
    "ERR_SOD_VIOLATION": 403,
    "ERR_INVOICE_EXCEEDS_LIMIT": 422,
    "ERR_INVOICE_NOT_EDITABLE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message


def not_found(what):
    return ApiError("ERR_NOT_FOUND", f"{what} not found")


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)

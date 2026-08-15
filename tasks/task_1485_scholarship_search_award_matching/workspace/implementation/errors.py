"""Error catalog and API exception type. Error IDs/HTTP statuses per PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_DATE_RANGE": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PROGRAM_NOT_OPEN": 409,
    "ERR_WINDOW_NOT_OPEN": 422,
    "ERR_DEADLINE_PASSED": 422,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_COMPONENT_INCOMPLETE": 422,
    "ERR_INELIGIBLE_STUDENT": 422,
    "ERR_CYCLE_WINDOW_OVERLAP": 409,
    "ERR_REVIEWER_DUPLICATE_SCORE": 409,
    "ERR_CONFLICT_OF_INTEREST": 422,
    "ERR_QUORUM_NOT_MET": 422,
    "ERR_AWARD_NOT_ACCEPTED": 409,
    "ERR_INSUFFICIENT_FUNDS": 422,
    "ERR_DISBURSEMENT_WINDOW_OVERLAP": 409,
    "ERR_AMOUNT_EXCEEDS_REMAINING": 422,
    "ERR_DISBURSEMENT_TOO_EARLY": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ADJUSTMENT_EXCEEDS_DISBURSED": 422,
    "ERR_RENEWAL_NOT_ELIGIBLE": 409,
    "ERR_MAX_RENEWALS_REACHED": 422,
    "ERR_DUPLICATE_RENEWAL_EVALUATION": 409,
    "ERR_TYL_NOT_WAIVABLE": 422,
    "ERR_REPORT_INCOMPLETE": 422,
}


def raise_err(error_id, message=""):
    raise ApiError(error_id, ERR[error_id], message or error_id)

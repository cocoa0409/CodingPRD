"""Error catalogue (PRD 5) and the exception type every refusal raises."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_SCOPE": 403,
    "ERR_SELF_DISPOSITION_FORBIDDEN": 403,
    "ERR_FIDUCIARY_BOUNDARY_VIOLATION": 403,
    # existence
    "ERR_EMPLOYER_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_REMITTANCE_NOT_FOUND": 404,
    "ERR_EXEMPTION_NOT_FOUND": 404,
    "ERR_EXCESS_CASE_NOT_FOUND": 404,
    "ERR_PENALTY_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_FUND_OPTION_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    # optimistic concurrency
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_STALE_EMPLOYER_VERSION": 412,
    # uniqueness / configuration
    "ERR_DUPLICATE_EIN": 409,
    "ERR_DUPLICATE_FUND_CODE": 409,
    "ERR_DUPLICATE_PROGRAM_YEAR": 409,
    "ERR_PROGRAM_YEAR_NOT_CONFIGURED": 409,
    # lifecycle state
    "ERR_REGISTRATION_STATE_INVALID": 409,
    "ERR_EXEMPTION_STATE_INVALID": 409,
    "ERR_ENROLLMENT_STATE_INVALID": 409,
    "ERR_EMPLOYER_NOT_REGISTERED": 409,
    "ERR_REMITTANCE_STATE_INVALID": 409,
    "ERR_ACCOUNT_CLOSED": 409,
    "ERR_ACCOUNT_RESTRICTED": 409,
    "ERR_CLOSURE_STATE_INVALID": 409,
    "ERR_EXCESS_CASE_STATE_INVALID": 409,
    "ERR_PENALTY_STATE_INVALID": 409,
    "ERR_TRANSFER_STATE_INVALID": 409,
    # enforcement interlock
    "ERR_ENFORCEMENT_HOLD": 409,
    # referential / cross-aggregate coherence
    "ERR_FUND_NOT_AVAILABLE": 409,
    "ERR_ENROLLMENT_NOT_DEDUCTIBLE": 409,
    "ERR_ACCOUNT_OWNER_MISMATCH": 409,
    "ERR_NO_DEFAULT_FUND_AVAILABLE": 409,
    # occupancy / uniqueness / frequency
    "ERR_PAY_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_EXEMPTION_PERIOD_OVERLAP": 409,
    "ERR_ROLLOVER_FREQUENCY_LIMIT": 409,
    # temporal windows
    "ERR_EXEMPTION_WINDOW_CLOSED": 409,
    "ERR_OPT_OUT_WINDOW_CLOSED": 409,
    "ERR_PERMISSIBLE_WITHDRAWAL_WINDOW_CLOSED": 409,
    "ERR_CORRECTION_DEADLINE_PASSED": 409,
    "ERR_ROLLOVER_WINDOW_EXPIRED": 409,
    "ERR_CURE_PERIOD_ACTIVE": 409,
    # arithmetic coherence
    "ERR_ALLOCATION_TOTAL_INVALID": 409,
    "ERR_DEDUCTION_AMOUNT_MISMATCH": 409,
    "ERR_REMITTANCE_TOTAL_MISMATCH": 409,
    "ERR_RATE_OUT_OF_BOUNDS": 409,
    # fiscal sufficiency
    "ERR_INSUFFICIENT_ACCOUNT_BALANCE": 402,
    "ERR_RESIDUAL_BALANCE_PRESENT": 409,
    # generic routing fallback (never part of the documented catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

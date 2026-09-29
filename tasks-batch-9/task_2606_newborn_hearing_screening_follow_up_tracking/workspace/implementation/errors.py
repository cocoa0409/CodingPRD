"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # Authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_IDENTITY_MISMATCH": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # Existence
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_INFANT_NOT_FOUND": 404,
    "ERR_ENCOUNTER_NOT_FOUND": 404,
    "ERR_EPISODE_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_RISK_ENTRY_NOT_FOUND": 404,
    "ERR_TASK_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    # Concurrency
    "ERR_STALE_INFANT_VERSION": 412,
    "ERR_STALE_FACILITY_VERSION": 412,
    # State
    "ERR_INFANT_ALREADY_DISCHARGED": 409,
    "ERR_EPISODE_NOT_SCHEDULABLE": 409,
    "ERR_APPOINTMENT_NOT_OPEN": 409,
    "ERR_EVALUATION_INVALID_STATE": 409,
    "ERR_REFERRAL_INVALID_STATE": 409,
    "ERR_TASK_INVALID_STATE": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_PERIOD_ALREADY_CLOSED": 409,
    "ERR_FACILITY_SUSPENDED": 409,
    "ERR_EARLIER_PERIOD_OPEN": 409,
    # Safety / attestation
    "ERR_GUARDIAN_CONSENT_REFUSED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_OUTCOME_THRESHOLD_MISMATCH": 422,
    "ERR_NO_OPEN_RISK_FACTOR": 422,
    # Referential integrity
    "ERR_PROVIDER_NOT_CREDENTIALED": 409,
    "ERR_PROVIDER_TYPE_MISMATCH": 409,
    "ERR_SLOT_TYPE_MISMATCH": 409,
    "ERR_LINKAGE_MISMATCH": 409,
    "ERR_INFANT_NOT_REFERRED": 409,
    "ERR_FACILITY_TYPE_MISMATCH": 409,
    # Temporal
    "ERR_BIRTH_DATETIME_IN_FUTURE": 422,
    "ERR_TIMESTAMP_OUT_OF_RANGE": 422,
    "ERR_SLOT_IN_PAST": 422,
    "ERR_PERIOD_NOT_ENDED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PERIOD_OVERLAP": 409,
    # Constraint
    "ERR_SLOT_OVERLAP": 409,
    "ERR_FAMILY_BURDEN_BUFFER": 409,
    "ERR_NAVIGATOR_TRAVEL_BUFFER": 409,
    "ERR_ATTEMPT_LIMIT_REACHED": 409,
    "ERR_ACTIVE_EPISODE_EXISTS": 409,
    "ERR_DUPLICATE_BIRTH_SCREEN": 409,
    "ERR_DUPLICATE_REPORT": 409,
    "ERR_NEGATIVE_PENALTY_BALANCE": 422,
    # Capacity
    "ERR_SLOT_FULL": 409,
    "ERR_NAVIGATION_BUDGET_EXHAUSTED": 409,
    "ERR_NO_ELIGIBLE_NAVIGATOR": 409,
    "ERR_NAVIGATOR_AT_CAPACITY": 409,
    # Fallbacks
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unknown authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The caller's role may not perform this operation.",
    "ERR_IDENTITY_MISMATCH": "The caller's identity does not match the addressed resource.",
    "ERR_INVALID_REQUEST": "The request body failed schema validation.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are out of range.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id) or error_id
        self.status = status or ERROR_STATUS.get(error_id, 400)

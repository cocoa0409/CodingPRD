"""Error catalogue and the ApiError exception (PRD 5 / SCAFFOLD 1.6)."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_CONCESSION_PARTY": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_CONCESSIONAIRE_NOT_FOUND": 404,
    "ERR_CONCESSION_NOT_FOUND": 404,
    "ERR_DRAWDOWN_MILESTONE_NOT_FOUND": 404,
    "ERR_SERVICE_PERIOD_NOT_FOUND": 404,
    "ERR_PERFORMANCE_REPORT_NOT_FOUND": 404,
    "ERR_DEDUCTION_EVENT_NOT_FOUND": 404,
    "ERR_DEDUCTION_DISPUTE_NOT_FOUND": 404,
    "ERR_RELIEF_CLAIM_NOT_FOUND": 404,
    "ERR_RESERVE_TRANSACTION_NOT_FOUND": 404,
    "ERR_REFINANCING_EVENT_NOT_FOUND": 404,
    "ERR_ENFORCEMENT_ACTION_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 400,
    # optimistic concurrency
    "ERR_STALE_CONCESSION_VERSION": 412,
    "ERR_STALE_SERVICE_PERIOD_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CONCESSION_STATE_FORBIDS_OPERATION": 409,
    "ERR_CONCESSION_UNDER_ENFORCEMENT": 409,
    "ERR_RESERVE_WITHDRAWAL_FORBIDDEN": 409,
    "ERR_ENFORCEMENT_GROUND_NOT_ADMITTED": 422,
    # coherence
    "ERR_CROSS_ENTITY_MISMATCH": 409,
    "ERR_TRANSACTION_ALREADY_REVERSED": 409,
    "ERR_CANNOT_REVERSE_REVERSAL": 409,
    # time windows
    "ERR_RELIEF_NOTIFICATION_LATE": 422,
    "ERR_CURE_WINDOW_VIOLATION": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_SERVICE_PERIOD_OVERLAP": 409,
    "ERR_RELIEF_WINDOW_CONFLICT": 409,
    # uniqueness / rounds
    "ERR_DUPLICATE_PERIOD_INDEX": 409,
    "ERR_DISPUTE_ALREADY_OPEN": 409,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    # fiscal ceilings
    "ERR_COMMITMENT_EXCEEDED": 422,
    "ERR_ANNUAL_DEDUCTION_CAP_EXCEEDED": 422,
    "ERR_RELIEF_DAYS_CAP_EXCEEDED": 422,
    "ERR_GRANT_EXCEEDS_CLAIM": 422,
    "ERR_NO_REFINANCING_GAIN": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is unrecognised.",
    "ERR_ROLE_NOT_PERMITTED": "The presented role may not perform this operation.",
    "ERR_NOT_CONCESSION_PARTY": "The caller is not a party to the owning concession.",
    "ERR_SEGREGATION_OF_DUTIES": "The same user may not perform both halves of this control pair.",
    "ERR_INVALID_REQUEST": "The request body failed schema validation.",
    "ERR_INVALID_STATE_TRANSITION": "The target row is not in a state that admits this transition.",
    "ERR_CONCESSION_STATE_FORBIDS_OPERATION": "The owning concession's state forbids this operation.",
    "ERR_CONCESSION_UNDER_ENFORCEMENT": "The concession is under a live enforcement action.",
    "ERR_RESERVE_WITHDRAWAL_FORBIDDEN": "The lifecycle reserve withdrawal is not permitted.",
    "ERR_CROSS_ENTITY_MISMATCH": "The referenced rows do not belong together.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

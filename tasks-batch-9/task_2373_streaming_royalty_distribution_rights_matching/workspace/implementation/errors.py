"""Error catalogue (§5) and the exception type used to abort a request."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_RIGHTS_HOLDER_NOT_FOUND": 404,
    "ERR_WORK_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_USAGE_BATCH_NOT_FOUND": 404,
    "ERR_USAGE_LINE_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_POOL_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_STATEMENT_LINE_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_RATE_SCHEDULE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_WORK_IDENTIFIER": 409,
    "ERR_DUPLICATE_PERIOD_LABEL": 409,
    "ERR_DUPLICATE_POOL": 409,
    "ERR_DUPLICATE_STATEMENT": 409,
    "ERR_INVALID_USAGE_BATCH_STATE": 409,
    "ERR_INVALID_REGISTRATION_STATE": 409,
    "ERR_INVALID_POOL_STATE": 409,
    "ERR_INVALID_STATEMENT_STATE": 409,
    "ERR_INVALID_ENGAGEMENT_STATE": 409,
    "ERR_INVALID_RATE_SCHEDULE_STATE": 409,
    "ERR_INVALID_PERIOD_STATE": 409,
    "ERR_STALE_WORK_VERSION": 412,
    "ERR_STALE_PERIOD_VERSION": 412,
    "ERR_STATUTORY_RATE_FLOOR_BREACH": 422,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    "ERR_AUDIT_WINDOW_EXPIRED": 422,
    "ERR_INVALID_EFFECTIVE_PERIOD": 422,
    "ERR_COLLECTIVE_NOT_ELIGIBLE": 422,
    "ERR_RIGHT_TYPE_WORK_MISMATCH": 422,
    "ERR_SHARE_OVERSUBSCRIBED": 409,
    "ERR_RATE_SCHEDULE_OVERLAP": 409,
    "ERR_RATE_SHARE_SPLIT_INVALID": 422,
    "ERR_EMPTY_USAGE_BATCH": 422,
    "ERR_ZERO_PLAY_COUNT": 422,
    "ERR_EVIDENCE_ROUNDS_EXHAUSTED": 422,
    "ERR_DISPUTE_BY_CLAIMANT": 422,
    "ERR_NO_EFFECTIVE_RATE_SCHEDULE": 422,
    "ERR_DATA_PRODUCTION_INCOMPLETE": 422,
    "ERR_SETTLEMENT_EXCEEDS_ASSERTION": 422,
    "ERR_NO_STATEMENT_LINES": 422,
    "ERR_HOLDING_UNRESOLVED": 422,
    "ERR_UNRESOLVED_REGISTRATIONS": 422,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The caller's role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the referenced resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this caller from performing this action.",
    "ERR_INVALID_REQUEST": "The request body is structurally invalid.",
}


def not_found(error_id):
    raise ApiError(error_id)


def invalid(message="The request body is structurally invalid."):
    raise ApiError("ERR_INVALID_REQUEST", message)

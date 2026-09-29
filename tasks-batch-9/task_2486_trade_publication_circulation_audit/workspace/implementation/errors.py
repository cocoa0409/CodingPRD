"""Error catalogue (PRD 5) and the exception type carrying it."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_CONTRACT_OWNER": 403,
    # existence
    "ERR_PUBLICATION_NOT_FOUND": 404,
    "ERR_SUBSCRIBER_NOT_FOUND": 404,
    "ERR_SOURCE_DOCUMENT_NOT_FOUND": 404,
    "ERR_QUALIFICATION_REQUEST_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_MAKEGOOD_NOT_FOUND": 404,
    "ERR_SNAPSHOT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    # optimistic concurrency
    "ERR_STALE_PUBLICATION_VERSION": 412,
    "ERR_STALE_SUBSCRIBER_VERSION": 412,
    # state preconditions
    "ERR_STATEMENT_NOT_DRAFT": 409,
    "ERR_REQUEST_NOT_UNDER_REVIEW": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_SAMPLE_LIMIT_EXCEEDED": 409,
    "ERR_OPEN_FINDINGS_UNRESOLVED": 409,
    # safety / compliance
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_PUBLICATION_FROZEN": 409,
    "ERR_BREAKDOWN_STALE": 409,
    # evidentiary referential integrity
    "ERR_SOURCE_DOCUMENT_PURGED": 422,
    "ERR_SOURCE_DOCUMENT_SUBSCRIBER_MISMATCH": 422,
    "ERR_RESTATEMENT_NOT_REQUIRED": 409,
    # temporal
    "ERR_INVALID_PERIOD_RANGE": 422,
    "ERR_QUALIFICATION_WINDOW_OVERLAP": 409,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
    "ERR_AUDIT_WINDOW_CONFLICT": 409,
    "ERR_PERIOD_NOT_ELAPSED": 422,
    "ERR_RETENTION_NOT_ELAPSED": 409,
    # qualification / policy constraints
    "ERR_QUALIFICATION_RULES_INCOMPLETE": 409,
    "ERR_MANDATORY_CRITERION_NOT_MET": 422,
    "ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD": 422,
    "ERR_INFO_REQUEST_LIMIT_REACHED": 409,
    "ERR_RULE_DIMENSION_EXISTS": 409,
    "ERR_PAID_REQUIRES_PAYMENT": 422,
    "ERR_DIGITAL_SOURCE_UNCERTIFIED": 422,
    # fiscal
    "ERR_MAKEGOOD_POOL_EXCEEDED": 422,
    "ERR_NO_SHORTFALL_TO_SETTLE": 409,
    # transport level (not part of the domain catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the five declared roles.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_CONTRACT_OWNER": "The acting AdvertiserContact does not own this make-good obligation.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_INVALID_ENUM_VALUE": "A supplied enum value is outside its declared set.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the entity's current state.",
    "ERR_ALREADY_TERMINAL": "The target entity is already in a terminal state.",
    "ERR_NOT_FOUND": "No such resource.",
    "ERR_METHOD_NOT_ALLOWED": "Method not allowed for this path.",
    "ERR_INTERNAL": "Internal server error.",
}

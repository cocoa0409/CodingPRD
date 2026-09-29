"""Error catalogue (PRD section 5) and the ApiError exception."""

CATALOG = {
    # auth / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_PROVIDER_SCOPE_VIOLATION": 403,
    "ERR_SUBSTITUTE_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_REMITTANCE_NOT_FOUND": 404,
    "ERR_FOOD_CLAIM_NOT_FOUND": 404,
    "ERR_SUBSTITUTE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # optimistic concurrency
    "ERR_STALE_PROVIDER_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
    # own-entity state
    "ERR_INVALID_PROVIDER_STATE": 409,
    "ERR_INVALID_AGREEMENT_STATE": 409,
    "ERR_INVALID_ENROLLMENT_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_INVALID_VISIT_STATE": 409,
    "ERR_INVALID_REVIEW_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_REMITTANCE_STATE": 409,
    # cross-entity state and posture
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_PROVIDER_POSTURE_BLOCKED": 409,
    # business safety
    "ERR_SUBSTITUTE_CLEARANCE_EXPIRED": 422,
    "ERR_LICENSE_EXPIRED": 422,
    # business temporal
    "ERR_SUBSTITUTE_INTERVAL_CONFLICT": 409,
    "ERR_COACHING_WINDOW_SATURATED": 409,
    "ERR_CLAIM_PERIOD_DUPLICATE": 409,
    "ERR_CAP_DEADLINE_PASSED": 422,
    "ERR_VISIT_DATE_IN_PAST": 422,
    # business referential
    "ERR_CLAIM_LINE_ENROLLMENT_MISMATCH": 422,
    "ERR_MEAL_LINE_CHILD_UNKNOWN": 422,
    "ERR_RECEIVING_PROVIDER_INELIGIBLE": 422,
    # business constraint
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 409,
    "ERR_MEAL_CAP_EXCEEDED": 422,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_CHILD_REF": 409,
    "ERR_EXIT_TRANSITIONS_PENDING": 409,
    "ERR_CAP_REJECTION_LIMIT_NOT_REACHED": 409,
    # business fiscal
    "ERR_SUBSIDY_SLOTS_EXHAUSTED": 409,
    "ERR_CONTRACT_AUTHORIZATION_EXCEEDED": 402,
    # non-catalogued fallbacks
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not call this endpoint.",
    "ERR_PROVIDER_SCOPE_VIOLATION": "A provider may only address its own resources.",
    "ERR_SUBSTITUTE_SCOPE_VIOLATION": "A substitute may only address their own assignments.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this operator from acting here.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)

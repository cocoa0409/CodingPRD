"""Error catalogue (PRD section 5) and the ApiError exception type."""

ERROR_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_FORBIDDEN": 403,
    "ERR_STORE_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_REQUESTED_PRICE_MISMATCH": 422,
    # existence
    "ERR_MARKET_NOT_FOUND": 404,
    "ERR_COMPETITOR_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_MATCH_NOT_FOUND": 404,
    "ERR_OBSERVATION_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_RULE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    # referential coherence
    "ERR_MARKET_MISMATCH": 422,
    "ERR_NO_CONFIRMED_MATCH": 422,
    # state guards
    "ERR_INVALID_STATE": 409,
    "ERR_MARKET_POSTURE_BLOCKED": 409,
    "ERR_CONFIDENCE_BELOW_CONFIRM_THRESHOLD": 422,
    "ERR_MAX_REVIEW_ROUNDS": 409,
    "ERR_MAX_EVIDENCE_ROUNDS": 409,
    "ERR_COMPETITOR_NOT_ELIGIBLE": 422,
    # data sufficiency
    "ERR_INSUFFICIENT_INDEX_DATA": 422,
    "ERR_NO_COMPETITOR_BENCHMARK": 422,
    "ERR_NO_APPLICABLE_REPRICING_RULE": 422,
    "ERR_DUPLICATE_OBSERVATION_WINDOW": 409,
    "ERR_OBSERVATION_IN_FUTURE": 422,
    "ERR_CLAIM_WINDOW_EXPIRED": 422,
    # pricing safety / fiscal
    "ERR_MAP_FLOOR_VIOLATION": 422,
    "ERR_BRAND_REPRICING_RESTRICTED": 422,
    "ERR_CHANGE_FREQUENCY_LIMIT": 409,
    "ERR_EFFECTIVE_WINDOW_OVERLAP": 409,
    "ERR_CLAIM_NO_SAVINGS": 422,
    "ERR_CATEGORY_EXCLUDED": 422,
    "ERR_MATCH_DISCOUNT_CAP_EXCEEDED": 422,
    "ERR_OVERRIDE_AUTHORITY_EXCEEDED": 403,
    "ERR_OVERRIDE_BUDGET_EXCEEDED": 409,
    # printing capacity
    "ERR_PRINT_WINDOW_CONFLICT": 409,
    "ERR_PRINT_CAPACITY_EXCEEDED": 409,
    # optimistic concurrency
    "ERR_STALE_PRODUCT_VERSION": 412,
    "ERR_STALE_MARKET_VERSION": 412,
    # transport level fallbacks (not part of the PRD catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def err(error_id, message=None):
    """Build an ApiError with the catalogue HTTP status."""
    return ApiError(error_id, message)

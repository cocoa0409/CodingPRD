"""Error catalog (PRD 5 / scaffold 1.6) and the ApiError exception."""

ERROR_HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_STORE_SCOPE_VIOLATION": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_FIXTURE_PLAN_NOT_FOUND": 404,
    "ERR_SIZE_PROFILE_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_POSITION_NOT_FOUND": 404,
    "ERR_RECEIPT_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_PROMO_EVENT_NOT_FOUND": 404,
    "ERR_RECOMMENDATION_NOT_FOUND": 404,
    "ERR_ASSORTMENT_ACTION_NOT_FOUND": 404,
    "ERR_SNAPSHOT_NOT_FOUND": 404,
    # referential
    "ERR_CROSS_PROGRAM_REFERENCE": 422,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_PROGRAM_LOCKED": 409,
    "ERR_ITEM_LIFECYCLE_BLOCKED": 409,
    "ERR_STALE_RECEIPT_VERSION": 412,
    "ERR_STALE_POSITION_VERSION": 412,
    # business safety
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_PRESENTATION_MIN_NOT_MET": 409,
    # business constraint
    "ERR_FIXTURE_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_STORE_CODE": 409,
    "ERR_DUPLICATE_SKU_CODE": 409,
    "ERR_DUPLICATE_EVENT_CODE": 409,
    "ERR_DUPLICATE_POSITION": 409,
    "ERR_DUPLICATE_PROFILE_CODE": 409,
    "ERR_SIZE_CURVE_INVALID": 422,
    "ERR_SIZE_UNITS_MISMATCH": 422,
    "ERR_SIZE_CODE_UNKNOWN": 422,
    "ERR_ITEM_CLASS_MISMATCH": 422,
    "ERR_METHOD_MODEL_MISMATCH": 422,
    "ERR_SAME_STORE_TRANSFER": 422,
    "ERR_STORE_NOT_ELIGIBLE": 409,
    "ERR_STORE_HAS_INVENTORY": 409,
    "ERR_LINE_ALREADY_SHIPPED": 409,
    "ERR_TRANSFER_SIZE_INFEASIBLE": 422,
    "ERR_NO_ELIGIBLE_STORES": 422,
    "ERR_ZERO_NETWORK_NEED": 409,
    "ERR_NO_CLUSTER_POSITIONS": 422,
    "ERR_NO_FIXTURE_PLAN_IN_EFFECT": 422,
    # business temporal
    "ERR_FIXTURE_PLAN_OVERLAP": 409,
    "ERR_PROMO_WINDOW_CONFLICT": 409,
    "ERR_TRANSFER_EXPIRED": 409,
    # business fiscal
    "ERR_INSUFFICIENT_DONOR_UNITS": 409,
    "ERR_BENEFIT_RATIO_BELOW_THRESHOLD": 409,
    "ERR_RECEIPT_UNITS_EXCEEDED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognised X-User-ID / X-User-Role headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this endpoint.",
    "ERR_STORE_SCOPE_VIOLATION": "A StoreOperator may only act within its own store.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, "Request rejected: %s." % error_id
        )

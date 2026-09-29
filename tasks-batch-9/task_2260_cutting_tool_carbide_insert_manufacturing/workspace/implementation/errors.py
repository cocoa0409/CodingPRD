"""Error classes and the complete error catalogue (PRD section 5 / scaffold 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


HTTP_STATUS = {
    # auth / authz
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # schema
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_WEAR_CURVE": 422,
    "ERR_INVALID_LAYER_STACK": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_INVALID_PRODUCT_DERIVATION": 422,
    "ERR_BELOW_MIN_ORDER_QTY": 422,
    "ERR_UNIT_COUNT_MISMATCH": 422,
    # not found
    "ERR_GRADE_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_GEOMETRY_NOT_FOUND": 404,
    "ERR_RECIPE_NOT_FOUND": 404,
    "ERR_COATING_RUN_NOT_FOUND": 404,
    "ERR_WHEEL_NOT_FOUND": 404,
    "ERR_GRINDING_RUN_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_DOSSIER_NOT_FOUND": 404,
    "ERR_TRIAL_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # concurrency / uniqueness
    "ERR_STALE_PRODUCT_VERSION": 412,
    "ERR_STALE_CUSTOMER_VERSION": 412,
    "ERR_DUPLICATE_CODE": 409,
    # state
    "ERR_INVALID_GRADE_STATE": 409,
    "ERR_INVALID_BATCH_STATE": 409,
    "ERR_INVALID_GEOMETRY_STATE": 409,
    "ERR_INVALID_COATING_RUN_STATE": 409,
    "ERR_INVALID_WHEEL_STATE": 409,
    "ERR_INVALID_GRINDING_RUN_STATE": 409,
    "ERR_INVALID_PRODUCT_STATE": 409,
    "ERR_INVALID_DOSSIER_STATE": 409,
    "ERR_INVALID_TRIAL_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_JOB_STATE": 409,
    "ERR_INVALID_CUSTOMER_STATE": 409,
    # business safety
    "ERR_WHEEL_EXPIRED": 409,
    "ERR_WHEEL_REQUIRES_DRESSING": 409,
    "ERR_BATCH_QC_NOT_PASSED": 409,
    "ERR_PRODUCT_NOT_ORDERABLE": 409,
    # business referential
    "ERR_GRADE_NOT_QUALIFIED": 409,
    "ERR_GEOMETRY_NOT_RELEASED": 409,
    "ERR_COATING_NOT_VALIDATED": 409,
    "ERR_PINNED_REVISION_STALE": 409,
    "ERR_NO_PASSED_BATCH": 409,
    "ERR_PRODUCT_NOT_REGRINDABLE": 409,
    "ERR_INVALID_PREDECESSOR_CHAIN": 409,
    "ERR_NO_APPROVED_DOSSIER": 409,
    "ERR_OPEN_DEMAND_EXISTS": 409,
    # business temporal
    "ERR_CHAMBER_CAPACITY_EXCEEDED": 409,
    "ERR_CELL_DOUBLE_BOOKED": 409,
    "ERR_CELL_BUFFER_CONFLICT": 409,
    "ERR_WINDOW_NOT_ELAPSED": 409,
    # business constraint
    "ERR_EXPEDITE_NOT_ELIGIBLE": 409,
    "ERR_INSUFFICIENT_BATCH_UNITS": 409,
    "ERR_INSUFFICIENT_TRIALS": 409,
    "ERR_COMPOSITE_SCORE_BELOW_MINIMUM": 409,
    "ERR_INSUFFICIENT_WORKPIECE_COVERAGE": 409,
    "ERR_NO_REGRINDS_REMAINING": 409,
    # business fiscal
    "ERR_CUSTOMER_CREDIT_HOLD": 402,
    "ERR_INSUFFICIENT_REGRIND_CREDIT": 402,
    "ERR_CUSTOMER_CLOSED": 409,
    # fallback
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-ID header is absent or empty.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role is not authorised for this endpoint.",
    "ERR_CUSTOMER_SCOPE_VIOLATION": "A Customer caller may only act on its own resources.",
    "ERR_SEGREGATION_OF_DUTIES": "The decider may be neither the submitter nor a trial operator.",
    "ERR_INVALID_REQUEST": "The request body or query is invalid.",
    "ERR_NOT_FOUND": "No such resource.",
}

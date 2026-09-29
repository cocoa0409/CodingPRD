"""Error catalogue (PRD section 5) and the exception used to signal them."""

HTTP_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_CASE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_DETERMINANT_CODE": 422,
    "ERR_INVALID_THRESHOLD_CONFIG": 422,
    "ERR_WEIGHTS_NOT_NORMALIZED": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_PROTOCOL_VERSION_NOT_FOUND": 404,
    "ERR_ROLLOUT_NOT_FOUND": 404,
    "ERR_DISPATCHER_NOT_FOUND": 404,
    "ERR_CALL_RECORD_NOT_FOUND": 404,
    "ERR_SAMPLING_PERIOD_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_REBUTTAL_NOT_FOUND": 404,
    "ERR_HIGH_RISK_REVIEW_NOT_FOUND": 404,
    "ERR_COACHING_PLAN_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_REVIEW_VERSION": 412,
    "ERR_STALE_DISPATCHER_VERSION": 412,
    # state
    "ERR_REVIEW_NOT_SCORABLE": 409,
    "ERR_REVIEW_NOT_DISPUTABLE": 409,
    "ERR_REVIEW_NOT_FINALIZABLE": 409,
    "ERR_REVIEW_ALREADY_VOIDED": 409,
    "ERR_PERIOD_NOT_OPEN": 409,
    "ERR_PERIOD_LOCKED": 409,
    "ERR_VERSION_NOT_APPROVABLE": 409,
    "ERR_ROLLOUT_NOT_LIVEABLE": 409,
    "ERR_HRCR_NOT_SCORABLE": 409,
    "ERR_HRCR_NOT_SIGNABLE": 409,
    "ERR_REBUTTAL_ALREADY_DECIDED": 409,
    "ERR_PLAN_NOT_OPEN": 409,
    "ERR_SESSION_NOT_COMPLETABLE": 409,
    "ERR_SESSION_NOT_CANCELLABLE": 409,
    "ERR_REPORT_ALREADY_SUBMITTED": 409,
    # referential / scope
    "ERR_PROGRAM_SCOPE_MISMATCH": 409,
    "ERR_CALL_TYPE_MISMATCH": 409,
    "ERR_VERSION_NOT_CERTIFIABLE": 409,
    "ERR_CURRICULUM_VERSION_NOT_TRAINABLE": 409,
    "ERR_NO_PROTOCOL_VERSION_IN_FORCE": 409,
    # clinical safety
    "ERR_HIGH_RISK_SIGN_OFF_REQUIRED": 422,
    "ERR_SENTINEL_CLASSIFICATION_REQUIRED": 422,
    # overlap / temporal
    "ERR_PROTOCOL_WINDOW_OVERLAP": 409,
    "ERR_SESSION_WINDOW_OVERLAP": 409,
    "ERR_GOLIVE_WINDOW_NOT_OPEN": 422,
    "ERR_CALL_RECEIVED_IN_FUTURE": 422,
    "ERR_CALL_OUTSIDE_PERIOD": 422,
    "ERR_REBUTTAL_WINDOW_CLOSED": 422,
    "ERR_REVIEW_DEADLINE_PASSED": 422,
    "ERR_REPORT_WINDOW_INVALID": 422,
    # uniqueness / cardinality
    "ERR_DUPLICATE_CALL_REFERENCE": 409,
    "ERR_DUPLICATE_EMPLOYEE_CODE": 409,
    "ERR_DUPLICATE_HIGH_RISK_REVIEW": 409,
    "ERR_DUPLICATE_COACHING_PLAN": 409,
    "ERR_CALL_ALREADY_SELECTED": 409,
    "ERR_SAMPLING_MODE_MISMATCH": 409,
    "ERR_REBUTTAL_ROUNDS_EXHAUSTED": 409,
    # quota / readiness
    "ERR_SAMPLE_QUOTA_FILLED": 422,
    "ERR_SAMPLE_QUOTA_NOT_MET": 422,
    "ERR_ESCALATED_SAMPLING_REQUIRED": 422,
    "ERR_TRAINING_INCOMPLETE": 422,
    # empty aggregates
    "ERR_NO_ELIGIBLE_CALLS": 422,
    "ERR_NO_FINALIZED_REVIEWS_IN_WINDOW": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognized.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_CASE_OWNER": "The acting dispatcher does not own this case.",
    "ERR_SEGREGATION_OF_DUTIES": "The finalizing operator submitted the current score sheet.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, "Request rejected: %s." % error_id
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)

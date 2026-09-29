"""Error catalogue and the ApiError exception."""

ERROR_STATUS = {
    # rung 1 - authentication
    "ERR_UNAUTHENTICATED": 401,
    # rung 2 / rung 6 - authorisation and scope
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_OUT_OF_SCOPE": 403,
    # rung 3 / rung 5 - existence
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_RATE_SCHEDULE_NOT_FOUND": 404,
    "ERR_DECISION_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_ADDENDUM_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_ATTENDANCE_RECORD_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_PROGRESS_REPORT_NOT_FOUND": 404,
    "ERR_TRANSITION_PLAN_NOT_FOUND": 404,
    "ERR_FUNDING_CLAIM_NOT_FOUND": 404,
    "ERR_FISCAL_ACCOUNT_NOT_FOUND": 404,
    # rung 4 - request shape
    "ERR_INVALID_REQUEST": 400,
    # rung 7 - stale view guards
    "ERR_STALE_PLACEMENT_VERSION": 412,
    "ERR_STALE_SCHOOL_VERSION": 412,
    # rung 8 - state legality
    "ERR_INVALID_STATE_TRANSITION": 409,
    # rung 9 - referential consistency
    "ERR_ATTENDANCE_PLACEMENT_MISMATCH": 409,
    "ERR_PLACEMENT_LINKAGE_MISMATCH": 409,
    "ERR_ADDENDUM_PLACEMENT_MISMATCH": 409,
    "ERR_FUNDING_CLAIM_LINKAGE_MISMATCH": 409,
    # rung 10 - temporal and window integrity
    "ERR_BILLING_PERIOD_SHAPE": 409,
    "ERR_PERIOD_OUTSIDE_PLACEMENT": 409,
    "ERR_DUPLICATE_BILLING_PERIOD": 409,
    "ERR_RATE_SCHEDULE_NOT_EFFECTIVE": 409,
    "ERR_INVALID_PLACEMENT_WINDOW": 409,
    "ERR_DUPLICATE_PROGRESS_PERIOD": 409,
    # rung 11 - safety and compliance
    "ERR_LRE_DOCUMENTATION_INCOMPLETE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_RESIDENTIAL_NOT_AUTHORIZED": 409,
    "ERR_MEDICAID_CONSENT_MISSING": 409,
    "ERR_ATTENDANCE_NOT_VERIFIED": 409,
    "ERR_SCHOOL_NOT_APPROVED": 409,
    "ERR_TRANSITION_SERVICES_INCOMPLETE": 409,
    # rung 12 - structural constraints
    "ERR_PLACEMENT_DATE_OVERLAP": 409,
    "ERR_TRANSPORT_WINDOW_OVERLAP": 409,
    "ERR_RETURN_READINESS_NOT_MET": 409,
    "ERR_MAX_ROUNDS_EXCEEDED": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_HIGH_COST_THRESHOLD_NOT_MET": 409,
    "ERR_CONCURRENT_DISTRICT_PLACEMENT": 409,
    "ERR_EQUITABLE_FINDINGS_REQUIRED": 409,
    "ERR_TRANSPORT_NOT_ASSIGNED": 409,
    # rung 13 - fiscal capacity
    "ERR_INSUFFICIENT_FISCAL_AUTHORITY": 402,
    "ERR_ENCUMBRANCE_EXCEEDED": 402,
    "ERR_HIGH_COST_CAP_EXHAUSTED": 402,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not perform this operation.",
    "ERR_OUT_OF_SCOPE": "The acting identity may not reach this resource.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_STALE_PLACEMENT_VERSION": "The supplied placement version is stale.",
    "ERR_STALE_SCHOOL_VERSION": "The supplied school version is stale.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not legal from the current state.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        if message is None:
            message = DEFAULT_MESSAGE.get(
                error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
            )
        self.message = message


def fail(error_id, message=None):
    raise ApiError(error_id, message)

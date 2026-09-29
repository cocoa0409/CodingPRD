"""Error catalogue (PRD 5) and the exception used to abort a request."""

ERROR_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INSTITUTION_SCOPE_VIOLATION": 403,
    "ERR_BORROWER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_INSTITUTION_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_TARGET_MARKET_NOT_FOUND": 404,
    "ERR_BOARD_SEAT_NOT_FOUND": 404,
    "ERR_BORROWER_NOT_FOUND": 404,
    "ERR_LOAN_PRODUCT_NOT_FOUND": 404,
    "ERR_LOAN_NOT_FOUND": 404,
    "ERR_TA_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_IMPACT_REPORT_NOT_FOUND": 404,
    "ERR_MEASUREMENT_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # optimistic concurrency
    "ERR_STALE_INSTITUTION_VERSION": 412,
    "ERR_STALE_LOAN_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_APPLICATION_NOT_UNDER_REVIEW": 409,
    "ERR_LOAN_NOT_IN_UNDERWRITING": 409,
    "ERR_LOAN_NOT_DELINQUENT_90": 409,
    "ERR_MEASUREMENT_NOT_DRAFT": 409,
    "ERR_AWARD_NOT_AWARDED": 409,
    "ERR_COMMITMENT_NOT_PLEDGED": 409,
    "ERR_ENGAGEMENT_NOT_SCHEDULED": 409,
    "ERR_REPORT_NOT_DISPUTED": 409,
    # business safety
    "ERR_TA_PREREQUISITE_UNMET": 409,
    "ERR_UNDERWRITING_TIER_UNMET": 422,
    "ERR_POSTURE_NOT_COMPLIANT": 409,
    "ERR_INSTITUTION_NOT_CERTIFIED": 409,
    # business referential
    "ERR_TARGET_MARKET_NOT_APPROVED": 422,
    "ERR_ACCOUNTABILITY_NOT_SATISFIED": 422,
    "ERR_BORROWER_NOT_GEOCODED": 422,
    "ERR_TEST_VERDICT_PENDING": 422,
    "ERR_MATCH_COMMITMENTS_UNVERIFIED": 409,
    "ERR_NO_MATCH_COMMITMENTS": 422,
    # business constraint
    "ERR_DUPLICATE_EIN": 409,
    "ERR_MEASUREMENT_PERIOD_OVERLAP": 409,
    "ERR_TA_SLOT_CONFLICT": 409,
    "ERR_NO_MEASURABLE_LOANS": 422,
    "ERR_FINANCING_ACTIVITY_BELOW_MINIMUM": 422,
    # business temporal
    "ERR_PERIOD_BOUNDS_INVALID": 422,
    "ERR_PERIOD_END_IN_FUTURE": 422,
    # business fiscal
    "ERR_PRODUCT_CAP_EXCEEDED": 422,
    "ERR_DISBURSEMENT_EXCEEDS_APPROVED": 422,
    "ERR_PAYMENT_EXCEEDS_OUTSTANDING": 422,
    "ERR_MATCH_SHORTFALL": 422,
    "ERR_FEDERAL_SOURCE_INELIGIBLE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)

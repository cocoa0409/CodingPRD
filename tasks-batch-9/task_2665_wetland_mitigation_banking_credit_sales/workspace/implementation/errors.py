"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # auth / authorisation / schema
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_SPONSOR_NOT_FOUND": 404,
    "ERR_PERMITTEE_NOT_FOUND": 404,
    "ERR_IRT_MEMBER_NOT_FOUND": 404,
    "ERR_BANK_NOT_FOUND": 404,
    "ERR_PROSPECTUS_NOT_FOUND": 404,
    "ERR_WORK_PLAN_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_MONITORING_REPORT_NOT_FOUND": 404,
    "ERR_REMEDIAL_ACTION_NOT_FOUND": 404,
    "ERR_CREDIT_SALE_NOT_FOUND": 404,
    # ownership / duty
    "ERR_NOT_BANK_SPONSOR": 403,
    "ERR_NOT_SALE_PERMITTEE": 403,
    "ERR_MEMBER_RECUSED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # state
    "ERR_BANK_STATE_INVALID": 409,
    "ERR_PROSPECTUS_STATE_INVALID": 409,
    "ERR_WORK_PLAN_STATE_INVALID": 409,
    "ERR_MILESTONE_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    "ERR_REMEDIAL_STATE_INVALID": 409,
    "ERR_SALE_STATE_INVALID": 409,
    "ERR_BANK_SALES_FROZEN": 409,
    "ERR_BANK_SALES_RESTRICTED": 409,
    "ERR_BANK_SOLD_OUT": 409,
    "ERR_MILESTONES_INCOMPLETE": 409,
    # concurrency
    "ERR_STALE_BANK_VERSION": 412,
    # regulatory safety
    "ERR_EASEMENT_NOT_RECORDED": 422,
    "ERR_OUTSIDE_SERVICE_AREA": 422,
    "ERR_SERVICE_AREA_MISSING_SITE_HUC": 422,
    # temporal
    "ERR_MONITORING_WINDOW_OVERLAP": 409,
    "ERR_RESERVATION_HOLD_CONFLICT": 409,
    "ERR_MILESTONE_WINDOW_BUFFER": 409,
    "ERR_MILESTONE_WINDOW_NOT_OPEN": 409,
    "ERR_REMEDIAL_PAST_DUE": 409,
    # uniqueness / aggregate constraints
    "ERR_DUPLICATE_MONITORING_YEAR": 409,
    "ERR_DUPLICATE_MILESTONE_CODE": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_DUPLICATE_PERMIT_NUMBER": 409,
    "ERR_RELEASE_SCHEDULE_OVERSUBSCRIBED": 422,
    "ERR_STANDARD_WEIGHTS_INVALID": 422,
    "ERR_WORK_PLAN_ALREADY_APPROVED": 409,
    "ERR_PREDECESSOR_NOT_RELEASED": 409,
    # referential / dependency
    "ERR_PROSPECTUS_NOT_APPROVED": 422,
    "ERR_WORK_PLAN_MISSING": 422,
    "ERR_IRT_QUORUM_NOT_MET": 422,
    "ERR_NO_EFFECTIVE_STANDARDS": 422,
    "ERR_MEASUREMENT_MISSING": 422,
    "ERR_NO_ACCEPTED_MONITORING_REPORT": 422,
    "ERR_COMPLIANCE_FAILED": 422,
    "ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT": 422,
    # fiscal
    "ERR_INSUFFICIENT_CREDITS": 422,
    "ERR_INSUFFICIENT_ESCROW": 402,
    "ERR_STEWARDSHIP_UNDERFUNDED": 402,
    "ERR_PERFORMANCE_BOND_INSUFFICIENT": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)

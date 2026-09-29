"""Error catalogue and the ApiError exception (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _message_for(error_id)


# error_id -> HTTP status, exactly as the PRD section 5 catalogue declares.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_RETAILER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PRODUCT_MODEL_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_HAZARD_PATTERN_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_SECTION_REPORT_NOT_FOUND": 404,
    "ERR_RECALL_NOT_FOUND": 404,
    "ERR_RETAILER_NOT_FOUND": 404,
    "ERR_RETAILER_NOTIFICATION_NOT_FOUND": 404,
    "ERR_AUDIT_VISIT_NOT_FOUND": 404,
    "ERR_CONSUMER_NOTICE_NOT_FOUND": 404,
    "ERR_REMEDY_CLAIM_NOT_FOUND": 404,
    "ERR_PROGRESS_REPORT_NOT_FOUND": 404,
    "ERR_PENALTY_CASE_NOT_FOUND": 404,
    "ERR_STALE_PRODUCT_MODEL_VERSION": 412,
    "ERR_STALE_PENALTY_CASE_VERSION": 412,
    "ERR_INCIDENT_STATE_INVALID": 409,
    "ERR_PATTERN_STATE_INVALID": 409,
    "ERR_EVALUATION_STATE_INVALID": 409,
    "ERR_SECTION_REPORT_STATE_INVALID": 409,
    "ERR_RECALL_PLAN_STATE_INVALID": 409,
    "ERR_NOTIFICATION_STATE_INVALID": 409,
    "ERR_VISIT_STATE_INVALID": 409,
    "ERR_NOTICE_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_PROGRESS_REPORT_STATE_INVALID": 409,
    "ERR_PENALTY_CASE_STATE_INVALID": 409,
    "ERR_MODEL_CODE_TAKEN": 409,
    "ERR_DUPLICATE_DOCKET_ENTRY": 409,
    "ERR_DUPLICATE_RETAILER_NOTIFICATION": 409,
    "ERR_MODEL_POSTURE_FROZEN": 409,
    "ERR_NOTIFICATION_NOT_SATISFIED": 409,
    "ERR_NO_ACTIVE_STOP_SALE": 409,
    "ERR_SHELF_REMOVAL_UNVERIFIED": 409,
    "ERR_SHELF_UNITS_PRESENT": 422,
    "ERR_PATTERN_NOT_CONFIRMABLE": 422,
    "ERR_DETERMINATION_UNSUPPORTED": 422,
    "ERR_AUDIT_WINDOW_CONFLICT": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_REPORT_PERIOD_GAP": 422,
    "ERR_NOTICE_NOT_DUE": 409,
    "ERR_EMBARGO_ACTIVE": 409,
    "ERR_SELF_DUPLICATE_REFERENCE": 422,
    "ERR_DUPLICATE_CHAIN_FORBIDDEN": 422,
    "ERR_REMEDY_OPTION_NOT_OFFERED": 422,
    "ERR_DIRECT_NOTICE_REQUIRED": 422,
    "ERR_CONSUMER_NOTICE_NOT_RELEASED": 409,
    "ERR_PROGRESS_REPORT_REQUIRED": 422,
    "ERR_REACH_EXCEEDS_REGISTRY": 422,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 409,
    "ERR_OFFER_EXCEEDS_ASSESSMENT": 422,
    "ERR_UNITS_OUTSTANDING_EXCEEDED": 422,
    "ERR_EFFECTIVENESS_NOT_MET": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing, empty or unrecognised authentication headers.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to call this endpoint.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_RETAILER_SCOPE_VIOLATION": "A retailer representative may only act on its own notification.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting operator may not approve work it filed itself.",
}


def _message_for(error_id):
    if error_id in DEFAULT_MESSAGES:
        return DEFAULT_MESSAGES[error_id]
    words = error_id[4:] if error_id.startswith("ERR_") else error_id
    return words.replace("_", " ").capitalize() + "."


def raise_error(error_id, message=None):
    raise ApiError(error_id, ERROR_STATUS[error_id], message)

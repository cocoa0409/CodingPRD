"""Error catalogue (PRD section 5) and the exception used to raise them."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_PROJECT_SCOPE_MISMATCH": 403,
    "ERR_JURISDICTION_SCOPE_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_PROJECT_STATE_INVALID": 409,
    "ERR_CAR_STATE_INVALID": 409,
    "ERR_SURVEY_STATE_INVALID": 409,
    "ERR_SCOPE_OPTION_STATE_INVALID": 409,
    "ERR_CODE_TRIGGER_STATE_INVALID": 409,
    "ERR_PROCUREMENT_STATE_INVALID": 409,
    "ERR_RESERVATION_STATE_INVALID": 409,
    "ERR_OUTAGE_STATE_INVALID": 409,
    "ERR_INSPECTION_STATE_INVALID": 409,
    "ERR_INSPECTION_NOT_RESCHEDULABLE": 409,
    "ERR_SCOPE_OPTION_NOT_APPROVED": 409,
    "ERR_WARRANTY_STATE_INVALID": 409,
    "ERR_CONTRACT_STATE_INVALID": 409,
    "ERR_CAR_GROUP_MISMATCH": 409,
    "ERR_RESERVATION_ORDER_MISMATCH": 409,
    "ERR_CONTRACT_PROJECT_MISMATCH": 409,
    "ERR_CODE_TRIGGER_OPEN": 409,
    "ERR_SCOPE_TIER_BELOW_RECOMMENDATION": 409,
    "ERR_GROUP_SERVICE_FLOOR": 409,
    "ERR_TEMP_SERVICE_PLAN_INADEQUATE": 409,
    "ERR_PUNCH_LIST_REQUIRED": 409,
    "ERR_CAR_NOT_CODE_ACCEPTED": 409,
    "ERR_OUTAGE_BUFFER_CONFLICT": 409,
    "ERR_PREDECESSOR_NOT_COMPLETE": 409,
    "ERR_TENANT_NOTICE_LEAD_UNMET": 409,
    "ERR_INSPECTION_LEAD_UNMET": 409,
    "ERR_WINDOW_EXPIRED": 409,
    "ERR_CONCURRENCY_CAP_EXCEEDED": 409,
    "ERR_PROJECT_FROZEN": 409,
    "ERR_RESCHEDULE_LIMIT": 409,
    "ERR_REVISION_LIMIT": 409,
    "ERR_PROCUREMENT_NOT_INSTALLED": 409,
    "ERR_NO_ENROLLED_TRANSITIONS": 409,
    "ERR_STAGING_CAPACITY_EXCEEDED": 409,
    "ERR_SCOPE_BUDGET_EXCEEDED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH": "X-User-ID and X-User-Role headers are required and X-User-Role must name a declared role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this endpoint.",
    "ERR_PROJECT_SCOPE_MISMATCH": "The acting building representative does not represent the owning project.",
    "ERR_JURISDICTION_SCOPE_MISMATCH": "The acting inspector does not act for the governing jurisdiction.",
    "ERR_SEGREGATION_OF_DUTIES": "The surveyor of record may not countersign their own survey.",
    "ERR_NOT_FOUND": "The requested resource does not exist.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_STALE_PROJECT_VERSION": "expected_project_version does not match the project's current version.",
}

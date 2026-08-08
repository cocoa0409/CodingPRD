"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INMATE_NOT_FOUND": 404,
    "ERR_REFERRAL_RECORD_NOT_FOUND": 404,
    "ERR_RECORD_NOT_FOUND": 404,
    "ERR_RECORDS_FROZEN": 409,
    "ERR_INMATE_NOT_IN_CUSTODY": 409,
    "ERR_STALE_INMATE_VERSION": 412,
    "ERR_STALE_REFERRAL_VERSION": 412,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_INTAKE_SCREENING_OVERDUE": 422,
    "ERR_MAX_RETRIAGE_EXCEEDED": 409,
    "ERR_DOT_OBSERVATION_REQUIRED": 422,
    "ERR_KOP_OBSERVATION_FORBIDDEN": 422,
    "ERR_ORDER_NOT_ACTIVE": 409,
    "ERR_REFERRAL_NOT_AUTHORIZED": 409,
    "ERR_ESCORT_LEVEL_MISMATCH": 422,
    "ERR_TRANSPORT_LEAD_TIME_TOO_SHORT": 422,
    "ERR_CANCEL_CUTOFF_PASSED": 422,
    "ERR_MAX_DEFERRALS_EXCEEDED": 409,
    "ERR_PEER_REVIEW_WINDOW_EXPIRED": 422,
    "ERR_GRIEVANCE_FILING_WINDOW_EXPIRED": 422,
    "ERR_MAX_REMANDS_EXCEEDED": 409,
    "ERR_CHARGE_NOT_REVERSIBLE": 409,
    "ERR_RELEASE_PLAN_LEAD_TIME": 422,
    "ERR_MORTALITY_REVIEW_INCOMPLETE": 422,
    "ERR_SCHEDULE_CONFLICT": 409,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def err(error_id, message=None):
    return ApiError(error_id, message)

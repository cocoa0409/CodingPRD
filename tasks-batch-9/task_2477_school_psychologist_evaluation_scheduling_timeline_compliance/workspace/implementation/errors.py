"""Error catalogue (PRD §5) and the exception type carrying it."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_PSYCH_NOT_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    # existence
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_PSYCHOLOGIST_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_INSTRUMENT_NOT_FOUND": 404,
    "ERR_SEAT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_EXCLUSION_NOT_FOUND": 404,
    "ERR_MEETING_NOT_FOUND": 404,
    "ERR_BREACH_NOT_FOUND": 404,
    # concurrency
    "ERR_STALE_EVALUATION_VERSION": 412,
    # state
    "ERR_EVALUATION_STATE_INVALID": 409,
    "ERR_REFERRAL_STATE_INVALID": 409,
    "ERR_EXCLUSION_ALREADY_DECIDED": 409,
    "ERR_ORDER_STATE_INVALID": 409,
    "ERR_MEETING_STATE_INVALID": 409,
    "ERR_BREACH_STATE_INVALID": 409,
    "ERR_SEAT_STATE_INVALID": 409,
    "ERR_PSYCHOLOGIST_STATE_INVALID": 409,
    "ERR_CONSENT_NOT_ON_FILE": 409,
    "ERR_REPORT_NOT_FINAL": 409,
    "ERR_INTERPRETER_SESSION_MISSING": 409,
    "ERR_MEETING_NOT_DUE": 409,
    # licensing, credentialing and coverage
    "ERR_SCORING_LICENSE_INVALID": 422,
    "ERR_LICENSE_SEATS_EXHAUSTED": 409,
    "ERR_PSYCH_BUILDING_MISMATCH": 422,
    "ERR_LANGUAGE_CERT_MISSING": 422,
    "ERR_INTERN_SCOPE_VIOLATION": 422,
    "ERR_PSYCH_CASELOAD_OVER_CAP": 409,
    "ERR_NO_ELIGIBLE_PSYCHOLOGIST": 409,
    # scheduling and notice
    "ERR_PSYCH_CALENDAR_CONFLICT": 409,
    "ERR_SCHOOL_MEETING_CAPACITY_FULL": 409,
    "ERR_NOTICE_LEAD_INSUFFICIENT": 422,
    "ERR_RESCHEDULE_LIMIT_REACHED": 409,
    # consent and clock integrity
    "ERR_CONSENT_TIMESTAMP_FUTURE": 422,
    "ERR_WAIVER_NOT_APPLICABLE": 422,
    "ERR_EXCLUSION_ZERO_DAYS": 422,
    "ERR_DUPLICATE_BUILDING_CODE": 409,
    # fiscal and inventory
    "ERR_PROTOCOL_STOCK_INSUFFICIENT": 409,
    "ERR_RECEIPT_QUANTITY_EXCEEDS_ORDER": 422,
    "ERR_REMEDY_MINUTES_EXCEED_CAP": 422,
    # generic routing fallbacks (not part of the catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

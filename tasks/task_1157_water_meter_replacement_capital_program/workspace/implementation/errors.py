"""API error type. error_id / http_status values come from PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalog (id -> http status), PRD section 5.
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_CONTRACTOR_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_ACCOUNT_NUMBER_CONFLICT": 409,
    "ERR_METER_SERIAL_CONFLICT": 409,
    "ERR_AMI_ENDPOINT_SERIAL_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_WORK_ORDER_VERSION": 412,
    "ERR_PROGRAM_NOT_ACTIVE": 422,
    "ERR_CRITICAL_CHANNEL_REQUIRED": 422,
    "ERR_FORCED_ENTRY_NOT_AUTHORIZED": 422,
    "ERR_BENCH_TEST_REQUIRED": 422,
    "ERR_NOTICE_WINDOW_NOT_MET": 422,
    "ERR_APPOINTMENT_SLOT_PAST": 422,
    "ERR_WAVE_WINDOW_OVERLAP": 409,
    "ERR_CREW_WINDOW_FULL": 409,
    "ERR_WAVE_CAPACITY_EXCEEDED": 422,
    "ERR_ACCOUNT_ALREADY_IN_PROGRAM": 409,
    "ERR_OPEN_COMPLAINT_EXISTS": 409,
    "ERR_OPEN_NO_ACCESS_CASE": 409,
    "ERR_ESCALATION_STEP_REQUIRED": 422,
    "ERR_CONTRACTOR_NOT_ACTIVE": 422,
    "ERR_CROSS_PROGRAM_REFERENCE": 422,
    "ERR_ACCOUNT_WORK_ORDER_MISMATCH": 422,
    "ERR_METER_NOT_AVAILABLE": 422,
    "ERR_READING_SEQUENCE_INVALID": 422,
    "ERR_RECONCILE_READINGS_INCOMPLETE": 422,
    "ERR_COMPLAINT_VARIANCE_BELOW_THRESHOLD": 422,
    "ERR_BUDGET_COMMITMENT_EXCEEDED": 422,
    "ERR_BUDGET_AVAILABLE_EXCEEDED": 422,
    "ERR_INVOICE_PERIOD_EMPTY": 422,
}


def raise_err(error_id, message):
    raise ApiError(error_id, ERR[error_id], message)

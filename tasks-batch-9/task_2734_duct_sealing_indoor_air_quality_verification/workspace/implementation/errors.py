"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6)."""

ERROR_STATUS = {
    # --- auth ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_UTILITY_PROGRAM_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_DUCT_SYSTEM_NOT_FOUND": 404,
    "ERR_LEAKAGE_TEST_NOT_FOUND": 404,
    "ERR_SEAL_JOB_NOT_FOUND": 404,
    "ERR_VERIFICATION_REPORT_NOT_FOUND": 404,
    "ERR_REBATE_CLAIM_NOT_FOUND": 404,
    "ERR_COMFORT_COMPLAINT_NOT_FOUND": 404,
    # --- request validity ---
    "ERR_INVALID_REQUEST": 400,
    # --- state ---
    "ERR_LEAKAGE_TEST_INVALID_STATE": 409,
    "ERR_SEAL_JOB_INVALID_STATE": 409,
    "ERR_DUCT_SYSTEM_INVALID_STATE": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_COMPLAINT_INVALID_STATE": 409,
    # --- concurrency ---
    "ERR_STALE_DUCT_SYSTEM_VERSION": 412,
    "ERR_STALE_SEAL_JOB_VERSION": 412,
    # --- combustion / project safety ---
    "ERR_COMBUSTION_SAFETY_REQUIRED": 422,
    "ERR_COMBUSTION_SPILLAGE_FAIL": 422,
    "ERR_PROJECT_SAFETY_HOLD": 422,
    "ERR_INJECTION_PRESSURE_LIMIT": 422,
    # --- cross entity coherence ---
    "ERR_PRE_TEST_SYSTEM_MISMATCH": 422,
    "ERR_TEST_PHASE_MISMATCH": 422,
    "ERR_RETEST_TARGET_INVALID": 422,
    "ERR_DUCT_SYSTEM_EXCLUDED": 422,
    "ERR_ASBESTOS_SCREENING_REQUIRED": 422,
    "ERR_PROGRAM_MISMATCH": 422,
    # --- structural / completeness ---
    "ERR_TECHNICIAN_NOT_CERTIFIED": 422,
    "ERR_CERTIFICATION_EXPIRED": 422,
    "ERR_MASKING_INCOMPLETE": 422,
    "ERR_NO_AIRFLOW_READINGS": 422,
    "ERR_SAMPLE_SEQUENCE_INVALID": 422,
    "ERR_DUPLICATE_READING_SEQ": 422,
    # --- interval / window ---
    "ERR_TECHNICIAN_SCHEDULE_CONFLICT": 409,
    "ERR_TEST_WINDOW_CONFLICT": 409,
    "ERR_RETEST_WINDOW_ELAPSED": 409,
    # --- fiscal / performance ---
    "ERR_GUARANTEE_NOT_MET": 422,
    "ERR_REBATE_REDUCTION_BELOW_PROGRAM_MINIMUM": 422,
    "ERR_PROGRAM_BUDGET_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-ID header is absent or empty.",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted to perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this user from performing this step.",
    "ERR_INVALID_REQUEST": "The request payload or query string is invalid.",
}


class ApiError(Exception):
    """An error that maps onto the documented error catalogue."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super().__init__(self.message)

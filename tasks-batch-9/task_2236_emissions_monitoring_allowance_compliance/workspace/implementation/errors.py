"""Error catalogue (PRD section 5).

Every error id maps to exactly one HTTP status. Handlers raise
:class:`ApiError` via :func:`fail`; ``app.py`` turns it into the error envelope.
"""


ERROR_STATUS = {
    # --- authentication / authorization -------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FACILITY_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # --- request shape ------------------------------------------------------
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # --- existence ----------------------------------------------------------
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_MONITORING_SYSTEM_NOT_FOUND": 404,
    "ERR_DAILY_CALIBRATION_NOT_FOUND": 404,
    "ERR_RATA_TEST_NOT_FOUND": 404,
    "ERR_OPERATING_HOUR_NOT_FOUND": 404,
    "ERR_FUEL_SAMPLE_NOT_FOUND": 404,
    "ERR_QUARTERLY_REPORT_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_PERMIT_LIMIT_NOT_FOUND": 404,
    "ERR_EXCESS_EVENT_NOT_FOUND": 404,
    "ERR_ALLOWANCE_ACCOUNT_NOT_FOUND": 404,
    "ERR_ALLOWANCE_TRANSACTION_NOT_FOUND": 404,
    "ERR_CONTROL_OUTAGE_NOT_FOUND": 404,
    # --- optimistic concurrency --------------------------------------------
    "ERR_STALE_MONITORING_SYSTEM_VERSION": 412,
    "ERR_STALE_REPORT_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    # --- state / uniqueness -------------------------------------------------
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_DUPLICATE_REPORT_PERIOD": 409,
    "ERR_DUPLICATE_MONITORING_SYSTEM": 409,
    "ERR_DUPLICATE_ORISPL_CODE": 409,
    "ERR_DUPLICATE_OPERATING_HOUR": 409,
    "ERR_DUPLICATE_ALLOWANCE_ACCOUNT": 409,
    "ERR_DUPLICATE_PERMIT_LIMIT": 409,
    "ERR_ACCOUNT_TRUE_UP_LOCKED": 409,
    "ERR_UNIT_NOT_ONLINE": 409,
    "ERR_MONITOR_OUT_OF_CONTROL": 409,
    "ERR_MONITOR_NOT_CERTIFIED": 409,
    "ERR_CALIBRATION_NOT_CURRENT": 409,
    "ERR_FUEL_SAMPLE_NOT_ANALYZED": 409,
    "ERR_FUEL_ANALYSIS_INVALIDATED": 409,
    "ERR_TRUE_UP_BEFORE_DEADLINE": 409,
    "ERR_REPORTS_NOT_ALL_ACCEPTED": 409,
    "ERR_RA_BASIS_NOT_PERMITTED": 409,
    "ERR_RETEST_ALREADY_EXISTS": 409,
    "ERR_RATA_WINDOW_OVERLAP": 409,
    "ERR_CONTROL_OUTAGE_OVERLAP": 409,
    "ERR_CONCURRENT_OUTAGE_LIMIT": 409,
    # --- operational safety / fiscal (422) ----------------------------------
    "ERR_RATA_WINDOW_IN_PAST": 422,
    "ERR_INSUFFICIENT_RATA_RUNS": 422,
    "ERR_HOUR_OUTSIDE_REPORT_PERIOD": 422,
    "ERR_METHOD_FIELD_MISMATCH": 422,
    "ERR_DATA_AVAILABILITY_BELOW_FLOOR": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_VALUE_OUT_OF_RANGE": 422,
    "ERR_NO_SUBSTITUTABLE_HOURS": 422,
    "ERR_BULK_SIZE_INVALID": 422,
    "ERR_INSUFFICIENT_ALLOWANCES": 422,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_INVALID_COUNTERPARTY": 422,
    "ERR_VINTAGE_YEAR_INVALID": 422,
    "ERR_PENALTY_TRANSACTION_NOT_CLIENT_CREATABLE": 422,
    "ERR_REASON_REQUIRED": 422,
}

_DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or unrecognized.",
    "ERR_UNAUTHORIZED": "The caller's role may not perform this operation.",
    "ERR_FACILITY_SCOPE_VIOLATION": "The caller may only act on its own facility.",
    "ERR_SEGREGATION_OF_DUTIES": "The signer may not be the preparer who submitted the report.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
    "ERR_INVALID_PAGINATION": "The pagination parameters are out of range.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGE.get(error_id) or error_id
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

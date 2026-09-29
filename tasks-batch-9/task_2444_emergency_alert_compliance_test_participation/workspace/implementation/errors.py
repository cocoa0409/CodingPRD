"""Error catalog (PRD 5).  error_id -> HTTP status."""

ERROR_CATALOG = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,

    "ERR_STATE_PLAN_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_RELAY_RULE_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_OUTAGE_NOT_FOUND": 404,
    "ERR_ALERT_EVENT_NOT_FOUND": 404,
    "ERR_WEA_NOTICE_NOT_FOUND": 404,
    "ERR_TEST_EVENT_NOT_FOUND": 404,
    "ERR_LOG_ENTRY_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,

    "ERR_ENGINEER_NOT_ASSIGNED": 403,
    "ERR_NOT_CERTIFYING_OFFICER": 403,

    "ERR_STALE_STATION_VERSION": 412,
    "ERR_STALE_TEST_EVENT_VERSION": 412,

    "ERR_PLAN_NOT_DRAFT": 409,
    "ERR_RELAY_RULE_NOT_ACTIVE": 409,
    "ERR_DEVICE_NOT_READY": 409,
    "ERR_DEVICE_DECOMMISSIONED": 409,
    "ERR_ASSIGNMENT_NOT_ACTIVE": 409,
    "ERR_ASSIGNMENT_NOT_DECOMMISSIONED": 409,
    "ERR_OUTAGE_NOT_REPAIRABLE": 409,
    "ERR_OUTAGE_NOT_IN_REPAIR": 409,
    "ERR_OUTAGE_NOT_RESTORED": 409,
    "ERR_ALERT_NOT_RELAY_PENDING": 409,
    "ERR_ACCESSIBILITY_ALREADY_VERIFIED": 409,
    "ERR_TEST_NOT_READY": 409,
    "ERR_TEST_NOT_LOGGED": 409,
    "ERR_TEST_ALREADY_FAILED_UNFILED": 409,
    "ERR_TEST_NO_ENTRIES": 409,
    "ERR_FILING_NOT_REVERSIBLE": 409,
    "ERR_FILING_NOT_SUBMITTED": 409,
    "ERR_INSPECTION_NOT_DRAFTABLE": 409,
    "ERR_INSPECTION_NOT_DRAFTED": 409,
    "ERR_INSPECTION_NOT_RESPONDED": 409,

    "ERR_FILINGS_SUSPENDED": 422,
    "ERR_POSTURE_NOT_TEST_ELIGIBLE": 422,

    "ERR_RECEIPT_COVERAGE_INCOMPLETE": 422,
    "ERR_LOG_ENTRY_SOURCE_UNKNOWN": 422,
    "ERR_DEVICE_STATION_MISMATCH": 422,

    "ERR_TEST_WINDOW_IN_PAST": 422,
    "ERR_TEST_WINDOW_OVERLAP": 409,
    "ERR_READINESS_WINDOW_NOT_OPEN": 422,
    "ERR_LOGGING_WINDOW_CLOSED": 422,
    "ERR_FILING_DEADLINE_PASSED": 422,
    "ERR_OUTAGE_DETECTED_IN_FUTURE": 422,
    "ERR_ALERT_RECEIVED_IN_FUTURE": 422,
    "ERR_INSPECTION_RESPONSE_WINDOW_CLOSED": 422,

    "ERR_DUPLICATE_CALL_SIGN": 409,
    "ERR_DUPLICATE_RELAY_PRIORITY": 409,
    "ERR_SOURCE_TYPE_ALREADY_COVERED": 409,
    "ERR_DEVICE_HAS_LIVE_ASSIGNMENTS": 409,
    "ERR_SEGREGATION_OF_DUTIES": 422,

    "ERR_PENALTY_CEILING_EXCEEDED": 422,
}


DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_INVALID_REQUEST": "The request body failed schema validation.",
    "ERR_ENGINEER_NOT_ASSIGNED": "The acting engineer is not assigned to the target station.",
    "ERR_NOT_CERTIFYING_OFFICER": "The acting operator is not the target station's certifying officer.",
}


class ApiError(Exception):
    """Domain error carrying an error_id from the catalog."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )

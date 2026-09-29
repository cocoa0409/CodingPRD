"""Error catalog (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id) or _humanize(error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)


def _humanize(error_id):
    """Readable default message; the machine contract stays the error_id."""
    text = error_id[4:] if error_id.startswith("ERR_") else error_id
    text = text.replace("_", " ").lower().strip()
    if not text:
        return error_id
    return text[0].upper() + text[1:] + "."


HTTP_STATUS = {
    # Authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_TECHNICIAN_IDENTITY_MISMATCH": 403,
    "ERR_STORE_SCOPE_VIOLATION": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    # Resolution
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_REFRIGERANT_TYPE_NOT_FOUND": 404,
    "ERR_SYSTEM_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_RECOVERY_EQUIPMENT_NOT_FOUND": 404,
    "ERR_CYLINDER_NOT_FOUND": 404,
    "ERR_SERVICE_RECORD_NOT_FOUND": 404,
    "ERR_LEAK_EVENT_NOT_FOUND": 404,
    "ERR_REPAIR_ATTEMPT_NOT_FOUND": 404,
    "ERR_VERIFICATION_TEST_NOT_FOUND": 404,
    "ERR_EXTENSION_REQUEST_NOT_FOUND": 404,
    "ERR_RETROFIT_PLAN_NOT_FOUND": 404,
    "ERR_REGULATORY_REPORT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    # Concurrency
    "ERR_STALE_SYSTEM_VERSION": 412,
    # Conflicts
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_SYSTEM_RETIRED": 409,
    "ERR_LEAK_EVENT_TERMINAL": 409,
    "ERR_SERVICE_RECORD_ALREADY_VOIDED": 409,
    "ERR_OPEN_LEAK_EVENT_EXISTS": 409,
    "ERR_TECHNICIAN_SCHEDULE_CONFLICT": 409,
    "ERR_EQUIPMENT_DECONTAMINATION_CONFLICT": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    # Business rules
    "ERR_TECHNICIAN_SUSPENDED": 422,
    "ERR_TECHNICIAN_CERT_EXPIRED": 422,
    "ERR_TECHNICIAN_CERT_TYPE_INVALID": 422,
    "ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED": 422,
    "ERR_RECOVERY_EQUIPMENT_INCOMPATIBLE": 422,
    "ERR_SEGREGATION_OF_DUTIES_VERIFICATION": 422,
    "ERR_SEGREGATION_OF_DUTIES_INSPECTION": 422,
    "ERR_REFRIGERANT_TYPE_MISMATCH": 422,
    "ERR_UNRECLAIMED_REFRIGERANT_REUSE": 422,
    "ERR_CROSS_STORE_RESOURCE": 422,
    "ERR_LEAK_EVENT_SYSTEM_MISMATCH": 422,
    "ERR_REPAIR_ATTEMPT_NOT_CURRENT": 422,
    "ERR_EXTENSION_REASON_NOT_APPLICABLE": 422,
    "ERR_TARGET_REFRIGERANT_PROHIBITED": 422,
    "ERR_RETROFIT_TARGET_REQUIRED": 422,
    "ERR_TIMESTAMP_AFTER_CLOCK": 422,
    "ERR_SERVICE_DATE_OUT_OF_RANGE": 422,
    "ERR_REPAIR_BEFORE_DETECTION": 422,
    "ERR_EXTENSION_WINDOW_CLOSED": 422,
    "ERR_GRANTED_DAYS_EXCEED_REQUESTED": 422,
    "ERR_EXTENSION_DAY_CAP_EXCEEDED": 422,
    "ERR_RETROFIT_INCOMPATIBLE": 422,
    "ERR_CYLINDER_FILL_LIMIT_EXCEEDED": 422,
    "ERR_INSUFFICIENT_CYLINDER_CONTENTS": 422,
    "ERR_CHARGE_EXCEEDS_NAMEPLATE": 422,
    "ERR_NEGATIVE_SYSTEM_CHARGE": 422,
    "ERR_SYSTEM_CHARGE_NOT_RECOVERED": 422,
    "ERR_OPEN_LEAK_EVENT_BLOCKS_RETIREMENT": 422,
    "ERR_RECLAIM_QUANTITY_EXCEEDS_SHIPPED": 422,
    "ERR_RECLAIM_PURITY_NOT_VERIFIED": 422,
    "ERR_VOID_NOT_PERMITTED": 422,
    "ERR_PLAN_COST_OUT_OF_RANGE": 422,
    # Fallback for unroutable requests
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The authenticated role may not perform this operation.",
    "ERR_INVALID_REQUEST": "The request body or query is invalid.",
}


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)

"""Error catalogue and exception type (PRD section 5)."""

ERROR_HTTP = {
    # Authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NURSE_NOT_ASSIGNED": 403,
    "ERR_PATIENT_NOT_OWNER": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    # Existence
    "ERR_CENTER_NOT_FOUND": 404,
    "ERR_CHAIR_NOT_FOUND": 404,
    "ERR_NURSE_NOT_FOUND": 404,
    "ERR_DRUG_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_TEMPLATE_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_PREPARATION_NOT_FOUND": 404,
    "ERR_ADVERSE_EVENT_NOT_FOUND": 404,
    "ERR_LAB_RESULT_NOT_FOUND": 404,
    "ERR_REMINDER_NOT_FOUND": 404,
    # Optimistic concurrency
    "ERR_STALE_APPOINTMENT_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_STALE_PLAN_VERSION": 412,
    # State preconditions
    "ERR_INVALID_SCHEDULE_STATE": 409,
    "ERR_APPOINTMENT_TERMINAL": 409,
    "ERR_INVALID_AUTH_STATE": 409,
    "ERR_INVALID_PREPARATION_STATE": 409,
    "ERR_INVALID_ADVERSE_EVENT_STATE": 409,
    "ERR_PLAN_SUSPENDED": 409,
    "ERR_PLAN_COMPLETED": 409,
    "ERR_PLAN_SUPERSEDED": 409,
    "ERR_TEMPLATE_RETIRED": 409,
    "ERR_CHAIR_OUT_OF_SERVICE": 409,
    "ERR_LOT_NOT_AVAILABLE": 409,
    "ERR_REMINDER_ALREADY_ANSWERED": 409,
    # Referential coherence
    "ERR_PLAN_PATIENT_MISMATCH": 422,
    "ERR_TEMPLATE_DRUG_MISMATCH": 422,
    "ERR_TEMPLATE_CENTER_MISMATCH": 422,
    "ERR_TEMPLATE_TIER_MISMATCH": 422,
    "ERR_TEMPLATE_VERSION_STALE": 409,
    "ERR_CYCLE_OUT_OF_RANGE": 422,
    # Clinical safety
    "ERR_ADVERSE_EVENT_OPEN": 409,
    "ERR_LAB_RESULT_MISSING": 422,
    "ERR_LAB_RESULT_STALE": 422,
    "ERR_LAB_GATE_NOT_MET": 422,
    "ERR_PREP_STABILITY_SHORT": 422,
    "ERR_PATIENT_STEERING_HOLD": 409,
    # Authorization / fiscal
    "ERR_AUTH_NOT_APPROVED": 409,
    "ERR_AUTH_EXPIRED": 409,
    "ERR_AUTH_RESUBMIT_LIMIT": 409,
    # Temporal
    "ERR_SERVICE_DATE_IN_PAST": 422,
    "ERR_SAME_DAY_REQUIRES_ADDON": 422,
    "ERR_ADDON_DATE_MISMATCH": 422,
    "ERR_ADDON_CUTOFF_PASSED": 422,
    "ERR_OUTSIDE_OPERATING_HOURS": 422,
    "ERR_CHECK_IN_WRONG_DAY": 409,
    "ERR_PREP_TOO_EARLY": 422,
    "ERR_PATIENT_DOUBLE_BOOKED": 409,
    # Downstream readiness
    "ERR_PREPARATION_NOT_READY": 409,
    # Capacity / quota
    "ERR_URGENT_RESERVE_LIMIT": 409,
    "ERR_NO_CHAIR_CAPACITY": 409,
    "ERR_URGENT_RESERVE_UNAVAILABLE": 409,
    "ERR_NO_NURSE_ON_SHIFT": 409,
    "ERR_NURSE_ACUITY_EXCEEDED": 409,
    "ERR_REMINDER_CADENCE_EXCEEDED": 409,
    "ERR_NO_ELIGIBLE_LOT": 409,
    "ERR_INSUFFICIENT_DRUG_UNITS": 422,
    # Uniqueness
    "ERR_DUPLICATE_MRN": 409,
    # Fallback (unrouted paths / methods)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or carry an unknown role.",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted to perform this operation.",
    "ERR_NURSE_NOT_ASSIGNED": "The calling nurse is not the nurse assigned to this visit.",
    "ERR_PATIENT_NOT_OWNER": "The calling patient does not own this record.",
    "ERR_INVALID_REQUEST": "The request payload or query is malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

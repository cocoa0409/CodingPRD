"""Error catalogue (PRD section 5 / scaffold section 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_PHARMACY_SCOPE_VIOLATION": 403,
    "ERR_PATIENT_SCOPE_VIOLATION": 403,
    "ERR_COURIER_SCOPE_VIOLATION": 403,
    "ERR_PLAN_SCOPE_VIOLATION": 403,
    "ERR_HIPAA_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_DELIVERY_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_COURIER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_EXCEPTION_CASE_NOT_FOUND": 404,
    "ERR_PLAN_GRANT_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_ATTEMPT_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    "ERR_ORDER_NOT_READY": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_CUSTODY_STATE": 409,
    "ERR_INVALID_SETTLEMENT_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_INVALID_EXCEPTION_STATE": 409,
    "ERR_COURIER_SUSPENDED": 409,
    "ERR_COURIER_UNAVAILABLE": 409,
    "ERR_INVALID_COURIER_STATE": 409,
    "ERR_WINDOW_CLOSED": 409,
    "ERR_GRANT_NOT_APPLICABLE": 409,
    "ERR_STALE_WINDOW_VERSION": 412,
    "ERR_STALE_DELIVERY_VERSION": 412,
    "ERR_CONSENT_NOT_GRANTED": 409,
    "ERR_CONTROLLED_NOT_LICENSED": 409,
    "ERR_CONTROLLED_ZONE_PROHIBITED": 409,
    "ERR_COLD_CHAIN_UNSUPPORTED_ZONE": 409,
    "ERR_COURIER_NOT_COLD_CERTIFIED": 409,
    "ERR_COURIER_NOT_CONTROLLED_CERTIFIED": 409,
    "ERR_COURIER_ZONE_NOT_SERVED": 409,
    "ERR_COURIER_MODE_MISMATCH": 409,
    "ERR_COLD_SEAL_REQUIRED": 409,
    "ERR_SIGNATURE_REQUIRED": 409,
    "ERR_UNATTENDED_NOT_PERMITTED": 409,
    "ERR_ID_VERIFICATION_INSUFFICIENT": 409,
    "ERR_ZONE_NOT_SERVICED": 409,
    "ERR_ZONE_MISMATCH": 409,
    "ERR_WINDOW_MODE_MISMATCH": 409,
    "ERR_DUPLICATE_ACTIVE_DELIVERY": 409,
    "ERR_MAX_HOLDS_EXCEEDED": 409,
    "ERR_WINDOW_ELAPSED": 409,
    "ERR_WINDOW_INTERVAL_INVALID": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_COURIER_OVERLAP_CONFLICT": 409,
    "ERR_REATTEMPT_COOLDOWN_ACTIVE": 409,
    "ERR_WINDOW_FULL": 409,
    "ERR_NO_ELIGIBLE_COURIER": 409,
    "ERR_GRANT_COVERAGE_INSUFFICIENT": 409,
    "ERR_EXCEPTION_PENDING": 409,
    "ERR_OVERRIDE_ADJUDICATION_CONFLICT": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-ID header is absent or empty.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_PHARMACY_SCOPE_VIOLATION": "The acting pharmacy does not own this resource.",
    "ERR_PATIENT_SCOPE_VIOLATION": "The acting patient does not own this resource.",
    "ERR_COURIER_SCOPE_VIOLATION": "The acting courier does not own this resource.",
    "ERR_PLAN_SCOPE_VIOLATION": "The acting health plan does not own this resource.",
    "ERR_HIPAA_SCOPE_VIOLATION": "No assignment on this delivery permits disclosure.",
    "ERR_SEGREGATION_OF_DUTIES": "This operations user may not adjudicate this case.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed or violates a field constraint.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)

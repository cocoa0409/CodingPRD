"""Error catalogue and the ApiError exception carried through the request stack."""

ERROR_STATUS = {
    # --- authentication and authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SELF_DECISION_FORBIDDEN": 403,
    "ERR_NOT_PLAN_AUTHOR": 403,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    # --- existence ---
    "ERR_STAFF_MEMBER_NOT_FOUND": 404,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_HOTLINE_CALL_NOT_FOUND": 404,
    "ERR_RISK_ASSESSMENT_NOT_FOUND": 404,
    "ERR_SAFETY_PLAN_NOT_FOUND": 404,
    "ERR_PLAN_COMPONENT_NOT_FOUND": 404,
    "ERR_SHELTER_NOT_FOUND": 404,
    "ERR_SHELTER_UNIT_NOT_FOUND": 404,
    "ERR_SCREENING_REQUEST_NOT_FOUND": 404,
    "ERR_SHELTER_ADMISSION_NOT_FOUND": 404,
    "ERR_PROTECTIVE_ORDER_CASE_NOT_FOUND": 404,
    "ERR_LANDLORD_PARTNER_NOT_FOUND": 404,
    "ERR_HOUSING_REFERRAL_NOT_FOUND": 404,
    "ERR_DISCLOSURE_EVENT_NOT_FOUND": 404,
    # --- cross reference and optimistic concurrency ---
    "ERR_CROSS_REFERENCE_MISMATCH": 422,
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_STALE_CLIENT_VERSION": 412,
    "ERR_STALE_LANDLORD_VERSION": 412,
    # --- state ---
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_SCREENING_NOT_APPROVED": 409,
    "ERR_LOCATION_COMPROMISED": 409,
    "ERR_PLAN_HAS_BLOCKED_COMPONENT": 409,
    "ERR_PLAN_HAS_NO_COMPONENTS": 422,
    # --- safety and compliance ---
    "ERR_CONFIDENTIALITY_HOLD": 409,
    "ERR_IMMINENT_RISK_REFERRAL_FORBIDDEN": 409,
    "ERR_ADVOCATE_FROZEN": 409,
    "ERR_HMIS_CONSENT_ABSENT": 409,
    # --- referential and temporal ---
    "ERR_ROI_EXPIRED": 409,
    "ERR_NO_ACTIVE_SAFETY_PLAN": 409,
    "ERR_SUBSIDY_TYPE_MISMATCH": 422,
    "ERR_DUPLICATE_ADMISSION": 409,
    "ERR_INVALID_DATE_WINDOW": 422,
    "ERR_ADVOCATE_DOUBLE_BOOKED": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # --- constraint and capacity ---
    "ERR_UNIT_ACCESSIBILITY_MISMATCH": 422,
    "ERR_UNIT_COMPOSITION_MISMATCH": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_SAME_UNIT_RELOCATION": 422,
    "ERR_SHELTER_FULL": 409,
    "ERR_CASELOAD_LIMIT_EXCEEDED": 409,
    "ERR_UNIT_CAPACITY_EXCEEDED": 409,
    "ERR_LANDLORD_NO_UNITS_AVAILABLE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_SELF_DECISION_FORBIDDEN": "The acting staff member may not decide their own request.",
    "ERR_NOT_PLAN_AUTHOR": "Only the safety plan's author may perform this operation.",
    "ERR_INVALID_REQUEST": "The request body or query string is invalid.",
    "ERR_CROSS_REFERENCE_MISMATCH": "A referenced row belongs to a different owner.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not declared from the current state.",
}


class ApiError(Exception):
    """Raised anywhere in the request stack; rendered into the standard error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)

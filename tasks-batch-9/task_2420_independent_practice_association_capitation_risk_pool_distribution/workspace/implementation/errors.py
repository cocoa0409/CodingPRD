"""Error catalogue (PRD section 5 / scaffold section 1.6)."""


ERROR_HTTP = {
    # ---- auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # ---- request shape
    "ERR_INVALID_REQUEST": 400,
    # ---- existence
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_PHYSICIAN_NOT_FOUND": 404,
    "ERR_ENROLLEE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_FILE_NOT_FOUND": 404,
    "ERR_REMITTANCE_NOT_FOUND": 404,
    "ERR_RISK_POOL_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_RECOVERY_NOT_FOUND": 404,
    "ERR_SCORECARD_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    # ---- concurrency
    "ERR_STALE_ENROLLEE_VERSION": 412,
    "ERR_STALE_PHYSICIAN_VERSION": 412,
    # ---- state
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS": 409,
    "ERR_PANEL_CLOSED_TO_NEW": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CAPITATION_POSTURE_RESTRICTED": 409,
    # ---- constraint / uniqueness
    "ERR_DUPLICATE_TAX_ID": 409,
    "ERR_DUPLICATE_NPI": 409,
    "ERR_DUPLICATE_MEMBER_ID": 409,
    "ERR_COVERAGE_MONTH_DUPLICATE": 409,
    "ERR_ASSIGNMENT_PERIOD_OVERLAP": 409,
    "ERR_POOL_PERIOD_OVERLAP": 409,
    # ---- referential / safety / temporal / fiscal
    "ERR_AGREEMENT_MISMATCH": 422,
    "ERR_SPECIALTY_AGE_BAND_MISMATCH": 422,
    "ERR_CONTINUITY_OF_CARE_ACTIVE": 422,
    "ERR_ASSIGNMENT_BEFORE_COVERAGE": 422,
    "ERR_NO_POOL_FOR_SERVICE_DATE": 422,
    "ERR_SETTLEMENT_WINDOW_NOT_OPEN": 422,
    "ERR_POOL_SHARE_SUM_INVALID": 422,
    "ERR_ENROLLMENT_FILE_EMPTY": 422,
    "ERR_SCORECARD_NOT_FINAL": 422,
    "ERR_PANEL_NOT_TRANSFERRED": 422,
    "ERR_STOP_LOSS_NOT_ATTACHED": 422,
    "ERR_PANEL_CAPACITY_EXCEEDED": 422,
    "ERR_ALLOWED_EXCEEDS_BILLED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and X-User-Role must name a declared role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the resource this operation acts on.",
    "ERR_SEGREGATION_OF_DUTIES": "The adjudicating user may not be the submitting user.",
    "ERR_INVALID_REQUEST": "The request is malformed or a field is missing, mistyped or out of range.",
    "ERR_AGREEMENT_NOT_FOUND": "Delegation agreement not found.",
    "ERR_PHYSICIAN_NOT_FOUND": "Physician member not found.",
    "ERR_ENROLLEE_NOT_FOUND": "Enrollee not found.",
    "ERR_ASSIGNMENT_NOT_FOUND": "Member assignment not found.",
    "ERR_ENROLLMENT_FILE_NOT_FOUND": "Enrollment file not found.",
    "ERR_REMITTANCE_NOT_FOUND": "Capitation remittance not found.",
    "ERR_RISK_POOL_NOT_FOUND": "Risk pool not found.",
    "ERR_CLAIM_NOT_FOUND": "Downstream claim not found.",
    "ERR_RECOVERY_NOT_FOUND": "Stop-loss recovery not found.",
    "ERR_SCORECARD_NOT_FOUND": "Quality scorecard not found.",
    "ERR_DISTRIBUTION_NOT_FOUND": "Pool distribution not found.",
    "ERR_STALE_ENROLLEE_VERSION": "The supplied expected_enrollee_version is stale.",
    "ERR_STALE_PHYSICIAN_VERSION": "The supplied expected_physician_version is stale.",
    "ERR_AGREEMENT_NOT_ACTIVE": "The governing delegation agreement is not ACTIVE.",
    "ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS": "The target physician is not in credential_status ACTIVE.",
    "ERR_PANEL_CLOSED_TO_NEW": "The target physician's panel is not OPEN.",
    "ERR_INVALID_STATE_TRANSITION": "The requested state transition is not permitted.",
    "ERR_CAPITATION_POSTURE_RESTRICTED": "The agreement's capitation posture does not permit reopening a panel.",
    "ERR_DUPLICATE_TAX_ID": "payer_tax_id already exists on another delegation agreement.",
    "ERR_DUPLICATE_NPI": "npi already exists on another physician of this agreement.",
    "ERR_DUPLICATE_MEMBER_ID": "external_member_id already exists on another enrollee of this agreement.",
    "ERR_COVERAGE_MONTH_DUPLICATE": "The agreement already holds a live enrollment file for this coverage month.",
    "ERR_ASSIGNMENT_PERIOD_OVERLAP": "The new assignment interval overlaps an existing non-terminal assignment.",
    "ERR_POOL_PERIOD_OVERLAP": "The new pool period overlaps an existing pool of the same type.",
    "ERR_AGREEMENT_MISMATCH": "Cross-referenced resources belong to different delegation agreements.",
    "ERR_SPECIALTY_AGE_BAND_MISMATCH": "The physician's specialty does not suit the enrollee's age band.",
    "ERR_CONTINUITY_OF_CARE_ACTIVE": "The holding physician's continuity-of-care window is still open.",
    "ERR_ASSIGNMENT_BEFORE_COVERAGE": "The assignment effective_date falls outside the enrollee's coverage span.",
    "ERR_NO_POOL_FOR_SERVICE_DATE": "No risk pool of this agreement and pool_type covers the service date.",
    "ERR_SETTLEMENT_WINDOW_NOT_OPEN": "The pool's settlement window is not open yet.",
    "ERR_POOL_SHARE_SUM_INVALID": "professional_pool_share_bps and institutional_pool_share_bps must sum to 10000.",
    "ERR_ENROLLMENT_FILE_EMPTY": "The enrollment file has no rows, or no matched rows.",
    "ERR_SCORECARD_NOT_FINAL": "Every in-scope physician must hold a FINAL scorecard for the pool year.",
    "ERR_PANEL_NOT_TRANSFERRED": "The physician still holds live or in-flight assignments.",
    "ERR_STOP_LOSS_NOT_ATTACHED": "The enrollee's paid claim total does not exceed the attachment point.",
    "ERR_PANEL_CAPACITY_EXCEEDED": "The target physician's panel is already at max_panel_size.",
    "ERR_ALLOWED_EXCEEDS_BILLED": "allowed_cents exceeds the claim's billed_cents.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

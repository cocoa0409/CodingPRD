"""Error vocabulary of the Hospital-At-Home Program API (PRD section 5)."""


class ApiError(Exception):
    """Carries the error_id, HTTP status and human message of a rejected request."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# --- PRD section 5 error catalogue: 32 codes ------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_INVALID_ENUM = "ERR_INVALID_ENUM"
ERR_PATIENT_NOT_FOUND = "ERR_PATIENT_NOT_FOUND"
ERR_REFERRAL_NOT_FOUND = "ERR_REFERRAL_NOT_FOUND"
ERR_EPISODE_NOT_FOUND = "ERR_EPISODE_NOT_FOUND"
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_EPISODE_NOT_ACTIVE = "ERR_EPISODE_NOT_ACTIVE"
ERR_REFERRAL_ORIGIN_INELIGIBLE = "ERR_REFERRAL_ORIGIN_INELIGIBLE"
ERR_CONDITION_NOT_QUALIFYING = "ERR_CONDITION_NOT_QUALIFYING"
ERR_OUTSIDE_SERVICE_RADIUS = "ERR_OUTSIDE_SERVICE_RADIUS"
ERR_EVAL_WINDOW_EXPIRED = "ERR_EVAL_WINDOW_EXPIRED"
ERR_HOME_SAFETY_FAILED = "ERR_HOME_SAFETY_FAILED"
ERR_CONNECTIVITY_INSUFFICIENT = "ERR_CONNECTIVITY_INSUFFICIENT"
ERR_CAREGIVER_REQUIRED = "ERR_CAREGIVER_REQUIRED"
ERR_CONSENT_MISSING = "ERR_CONSENT_MISSING"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_WITNESS_REQUIRED = "ERR_WITNESS_REQUIRED"
ERR_COLD_CHAIN_EXCURSION = "ERR_COLD_CHAIN_EXCURSION"
ERR_VISIT_OVERLAP = "ERR_VISIT_OVERLAP"
ERR_DIET_INCOMPATIBLE = "ERR_DIET_INCOMPATIBLE"
ERR_NO_BEDS_AVAILABLE = "ERR_NO_BEDS_AVAILABLE"
ERR_KIT_UNAVAILABLE = "ERR_KIT_UNAVAILABLE"
ERR_REDELIVERY_LIMIT_EXCEEDED = "ERR_REDELIVERY_LIMIT_EXCEEDED"
ERR_APPEAL_LIMIT_EXCEEDED = "ERR_APPEAL_LIMIT_EXCEEDED"
ERR_MED_REC_UNSIGNED = "ERR_MED_REC_UNSIGNED"
ERR_DELIVERY_NOT_TERMINAL = "ERR_DELIVERY_NOT_TERMINAL"
ERR_RECONCILIATION_INCOMPLETE = "ERR_RECONCILIATION_INCOMPLETE"
ERR_NO_BILLABLE_DAYS = "ERR_NO_BILLABLE_DAYS"

HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_VALIDATION: 400,
    ERR_INVALID_ENUM: 422,
    ERR_PATIENT_NOT_FOUND: 404,
    ERR_REFERRAL_NOT_FOUND: 404,
    ERR_EPISODE_NOT_FOUND: 404,
    ERR_RESOURCE_NOT_FOUND: 404,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_STATE: 409,
    ERR_EPISODE_NOT_ACTIVE: 409,
    ERR_REFERRAL_ORIGIN_INELIGIBLE: 422,
    ERR_CONDITION_NOT_QUALIFYING: 422,
    ERR_OUTSIDE_SERVICE_RADIUS: 422,
    ERR_EVAL_WINDOW_EXPIRED: 422,
    ERR_HOME_SAFETY_FAILED: 422,
    ERR_CONNECTIVITY_INSUFFICIENT: 422,
    ERR_CAREGIVER_REQUIRED: 422,
    ERR_CONSENT_MISSING: 422,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_WITNESS_REQUIRED: 422,
    ERR_COLD_CHAIN_EXCURSION: 422,
    ERR_VISIT_OVERLAP: 409,
    ERR_DIET_INCOMPATIBLE: 422,
    ERR_NO_BEDS_AVAILABLE: 409,
    ERR_KIT_UNAVAILABLE: 409,
    ERR_REDELIVERY_LIMIT_EXCEEDED: 409,
    ERR_APPEAL_LIMIT_EXCEEDED: 409,
    ERR_MED_REC_UNSIGNED: 409,
    ERR_DELIVERY_NOT_TERMINAL: 409,
    ERR_RECONCILIATION_INCOMPLETE: 409,
    ERR_NO_BILLABLE_DAYS: 422,
}

DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
    ERR_FORBIDDEN_ROLE: "The acting role is not authorized for this endpoint.",
    ERR_VALIDATION: "A required field is missing or a bound was violated.",
    ERR_INVALID_ENUM: "An enum-typed field carries a value outside its declared value set.",
    ERR_PATIENT_NOT_FOUND: "The referenced patient does not exist.",
    ERR_REFERRAL_NOT_FOUND: "The referenced referral does not exist.",
    ERR_EPISODE_NOT_FOUND: "The referenced episode does not exist.",
    ERR_RESOURCE_NOT_FOUND: "The referenced resource does not exist.",
    ERR_STALE_VERSION: "The supplied expected version does not match the current version of the parent row.",
    ERR_INVALID_STATE: "The target row is not in a legal state for the requested transition.",
    ERR_EPISODE_NOT_ACTIVE: "The parent episode is not ACTIVE.",
    ERR_REFERRAL_ORIGIN_INELIGIBLE: "The referral origin is not eligible for home hospitalization.",
    ERR_CONDITION_NOT_QUALIFYING: "The qualifying condition code does not qualify for home hospitalization.",
    ERR_OUTSIDE_SERVICE_RADIUS: "The patient home lies outside the program service radius.",
    ERR_EVAL_WINDOW_EXPIRED: "The in-person physician evaluation falls outside the admission window.",
    ERR_HOME_SAFETY_FAILED: "The home safety assessment did not pass.",
    ERR_CONNECTIVITY_INSUFFICIENT: "The home broadband connectivity check did not pass.",
    ERR_CAREGIVER_REQUIRED: "A high-acuity referral requires a confirmed caregiver in the home.",
    ERR_CONSENT_MISSING: "Patient consent to home hospitalization has not been signed.",
    ERR_SEGREGATION_OF_DUTIES: "A controlled order may not be authorized by the identity that requested it.",
    ERR_WITNESS_REQUIRED: "A controlled delivery handoff requires a witness_staff_id.",
    ERR_COLD_CHAIN_EXCURSION: "The cold-chain excursion exceeds the permitted maximum.",
    ERR_VISIT_OVERLAP: "The requested visit interval collides with another visit of the same staff member.",
    ERR_DIET_INCOMPATIBLE: "The meal plan diet code is incompatible with the patient diet restriction.",
    ERR_NO_BEDS_AVAILABLE: "The inpatient unit has no available bed.",
    ERR_KIT_UNAVAILABLE: "The device kit is not available, or the episode already has a deployed kit.",
    ERR_REDELIVERY_LIMIT_EXCEEDED: "The redelivery cap for this order has been reached.",
    ERR_APPEAL_LIMIT_EXCEEDED: "The appeal cap for this claim has been reached.",
    ERR_MED_REC_UNSIGNED: "Medication reconciliation has not been signed for this episode.",
    ERR_DELIVERY_NOT_TERMINAL: "At least one delivery order of this episode is not in a terminal status.",
    ERR_RECONCILIATION_INCOMPLETE: "At least one component of the episode kit is still outstanding.",
    ERR_NO_BILLABLE_DAYS: "The episode has no billable days.",
}


def fail(error_id, message=None):
    """Raise the catalogued error with its declared HTTP status."""
    raise ApiError(error_id, HTTP_STATUS[error_id], message)

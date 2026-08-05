"""Error catalogue for the GLP-1 weight-loss telehealth API.

Every identifier and HTTP status is taken verbatim from PRD section 5
(Error Code Catalogue) and SCAFFOLD.yaml section 1.6.
"""

# --- error identifiers -----------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_VALIDATION = "ERR_VALIDATION"

ERR_PATIENT_NOT_FOUND = "ERR_PATIENT_NOT_FOUND"
ERR_PROVIDER_NOT_FOUND = "ERR_PROVIDER_NOT_FOUND"
ERR_PHARMACY_RESOURCE_NOT_FOUND = "ERR_PHARMACY_RESOURCE_NOT_FOUND"
ERR_CLINICAL_RECORD_NOT_FOUND = "ERR_CLINICAL_RECORD_NOT_FOUND"
ERR_FULFILLMENT_RECORD_NOT_FOUND = "ERR_FULFILLMENT_RECORD_NOT_FOUND"
ERR_BILLING_RECORD_NOT_FOUND = "ERR_BILLING_RECORD_NOT_FOUND"

ERR_STALE_PATIENT_VERSION = "ERR_STALE_PATIENT_VERSION"
ERR_STALE_PRESCRIPTION_VERSION = "ERR_STALE_PRESCRIPTION_VERSION"

ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_PRESCRIPTION_NOT_ACTIVE = "ERR_PRESCRIPTION_NOT_ACTIVE"
ERR_SUBSCRIPTION_NOT_ACTIVE = "ERR_SUBSCRIPTION_NOT_ACTIVE"

ERR_SCREENING_NOT_ELIGIBLE = "ERR_SCREENING_NOT_ELIGIBLE"
ERR_OPEN_ESCALATED_CHECK_IN = "ERR_OPEN_ESCALATED_CHECK_IN"
ERR_TITRATION_INTERVAL_NOT_MET = "ERR_TITRATION_INTERVAL_NOT_MET"
ERR_TITRATION_MAX_DOSE_REACHED = "ERR_TITRATION_MAX_DOSE_REACHED"
ERR_SECOND_SIGNER_REQUIRED = "ERR_SECOND_SIGNER_REQUIRED"
ERR_SECOND_SIGNER_CONFLICT = "ERR_SECOND_SIGNER_CONFLICT"
ERR_PRIOR_AUTH_REQUIRED = "ERR_PRIOR_AUTH_REQUIRED"
ERR_APPEAL_LIMIT_REACHED = "ERR_APPEAL_LIMIT_REACHED"

ERR_PROVIDER_NOT_ELIGIBLE = "ERR_PROVIDER_NOT_ELIGIBLE"
ERR_CONSULT_SLOT_CONFLICT = "ERR_CONSULT_SLOT_CONFLICT"
ERR_COACH_SLOT_CONFLICT = "ERR_COACH_SLOT_CONFLICT"

ERR_NO_ELIGIBLE_SUPPLY_LOT = "ERR_NO_ELIGIBLE_SUPPLY_LOT"
ERR_LOT_CAPACITY_EXCEEDED = "ERR_LOT_CAPACITY_EXCEEDED"
ERR_UNITS_EXCEED_LIMIT = "ERR_UNITS_EXCEED_LIMIT"

ERR_COACHING_CREDITS_EXHAUSTED = "ERR_COACHING_CREDITS_EXHAUSTED"
ERR_PAUSE_LIMIT_EXCEEDED = "ERR_PAUSE_LIMIT_EXCEEDED"


# --- error id -> HTTP status ----------------------------------------------
HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_VALIDATION: 400,
    ERR_PATIENT_NOT_FOUND: 404,
    ERR_PROVIDER_NOT_FOUND: 404,
    ERR_PHARMACY_RESOURCE_NOT_FOUND: 404,
    ERR_CLINICAL_RECORD_NOT_FOUND: 404,
    ERR_FULFILLMENT_RECORD_NOT_FOUND: 404,
    ERR_BILLING_RECORD_NOT_FOUND: 404,
    ERR_STALE_PATIENT_VERSION: 412,
    ERR_STALE_PRESCRIPTION_VERSION: 412,
    ERR_INVALID_STATE: 409,
    ERR_PRESCRIPTION_NOT_ACTIVE: 409,
    ERR_SUBSCRIPTION_NOT_ACTIVE: 409,
    ERR_SCREENING_NOT_ELIGIBLE: 409,
    ERR_OPEN_ESCALATED_CHECK_IN: 409,
    ERR_TITRATION_INTERVAL_NOT_MET: 409,
    ERR_TITRATION_MAX_DOSE_REACHED: 422,
    ERR_SECOND_SIGNER_REQUIRED: 422,
    ERR_SECOND_SIGNER_CONFLICT: 403,
    ERR_PRIOR_AUTH_REQUIRED: 409,
    ERR_APPEAL_LIMIT_REACHED: 422,
    ERR_PROVIDER_NOT_ELIGIBLE: 422,
    ERR_CONSULT_SLOT_CONFLICT: 409,
    ERR_COACH_SLOT_CONFLICT: 409,
    ERR_NO_ELIGIBLE_SUPPLY_LOT: 409,
    ERR_LOT_CAPACITY_EXCEEDED: 409,
    ERR_UNITS_EXCEED_LIMIT: 422,
    ERR_COACHING_CREDITS_EXHAUSTED: 402,
    ERR_PAUSE_LIMIT_EXCEEDED: 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by app.py."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "Authentication headers are missing or name an unrecognised role.",
    ERR_UNAUTHORIZED: "The acting role is not authorised for this operation.",
    ERR_VALIDATION: "The request body failed validation.",
    ERR_PATIENT_NOT_FOUND: "The referenced patient does not exist.",
    ERR_PROVIDER_NOT_FOUND: "The referenced provider does not exist.",
    ERR_PHARMACY_RESOURCE_NOT_FOUND: "The referenced pharmacy resource does not exist.",
    ERR_CLINICAL_RECORD_NOT_FOUND: "The referenced clinical record does not exist.",
    ERR_FULFILLMENT_RECORD_NOT_FOUND: "The referenced fulfilment record does not exist.",
    ERR_BILLING_RECORD_NOT_FOUND: "The referenced billing record does not exist.",
    ERR_STALE_PATIENT_VERSION: "expected_patient_version does not match the current patient version.",
    ERR_STALE_PRESCRIPTION_VERSION: "expected_prescription_version does not match the current prescription version.",
    ERR_INVALID_STATE: "The requested transition is not declared from the record's current state.",
    ERR_PRESCRIPTION_NOT_ACTIVE: "The governing prescription is not clinically active.",
    ERR_SUBSCRIPTION_NOT_ACTIVE: "The governing subscription is not active.",
    ERR_SCREENING_NOT_ELIGIBLE: "The cited screening is not eligible for this patient.",
    ERR_OPEN_ESCALATED_CHECK_IN: "An escalated check-in remains open for this prescription.",
    ERR_TITRATION_INTERVAL_NOT_MET: "The titration interval has not yet elapsed.",
    ERR_TITRATION_MAX_DOSE_REACHED: "The prescription is already at the top of the dose ladder.",
    ERR_SECOND_SIGNER_REQUIRED: "A second signing clinician is required for this dose level.",
    ERR_SECOND_SIGNER_CONFLICT: "The supplied second signer is not admissible.",
    ERR_PRIOR_AUTH_REQUIRED: "An approved prior authorisation is required to ship this order.",
    ERR_APPEAL_LIMIT_REACHED: "The appeal ceiling has already been reached.",
    ERR_PROVIDER_NOT_ELIGIBLE: "The named practitioner is not eligible for this operation.",
    ERR_CONSULT_SLOT_CONFLICT: "The requested consult window collides with another scheduled consult.",
    ERR_COACH_SLOT_CONFLICT: "The requested coaching window collides with another scheduled session.",
    ERR_NO_ELIGIBLE_SUPPLY_LOT: "No supply lot satisfies the routing selector.",
    ERR_LOT_CAPACITY_EXCEEDED: "The lot cannot cover this reservation.",
    ERR_UNITS_EXCEED_LIMIT: "units_requested exceeds the permitted ceiling.",
    ERR_COACHING_CREDITS_EXHAUSTED: "No coaching credits remain available.",
    ERR_PAUSE_LIMIT_EXCEEDED: "The cumulative pause ceiling has been reached.",
}

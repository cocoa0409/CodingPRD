"""Error catalogue and the ApiError exception carried through every request."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# --- authentication / authorization ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_ACQUIRER_SCOPE_VIOLATION = "ERR_ACQUIRER_SCOPE_VIOLATION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

# --- existence ---
ERR_PLATFORM_NOT_FOUND = "ERR_PLATFORM_NOT_FOUND"
ERR_ACQUIRER_NOT_FOUND = "ERR_ACQUIRER_NOT_FOUND"
ERR_MCC_DEFINITION_NOT_FOUND = "ERR_MCC_DEFINITION_NOT_FOUND"
ERR_MERCHANT_NOT_FOUND = "ERR_MERCHANT_NOT_FOUND"
ERR_RATE_PROGRAM_NOT_FOUND = "ERR_RATE_PROGRAM_NOT_FOUND"
ERR_RATE_VERSION_NOT_FOUND = "ERR_RATE_VERSION_NOT_FOUND"
ERR_WINDOW_NOT_FOUND = "ERR_WINDOW_NOT_FOUND"
ERR_BATCH_NOT_FOUND = "ERR_BATCH_NOT_FOUND"
ERR_RECORD_NOT_FOUND = "ERR_RECORD_NOT_FOUND"
ERR_RECLASS_REQUEST_NOT_FOUND = "ERR_RECLASS_REQUEST_NOT_FOUND"
ERR_INCENTIVE_PROGRAM_NOT_FOUND = "ERR_INCENTIVE_PROGRAM_NOT_FOUND"
ERR_ENROLLMENT_NOT_FOUND = "ERR_ENROLLMENT_NOT_FOUND"
ERR_AUDIT_NOT_FOUND = "ERR_AUDIT_NOT_FOUND"
ERR_FX_RATE_NOT_FOUND = "ERR_FX_RATE_NOT_FOUND"

# --- request shape ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# --- state ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_BATCH_NOT_OPEN = "ERR_BATCH_NOT_OPEN"
ERR_ENROLLMENT_CLOSED = "ERR_ENROLLMENT_CLOSED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"

# --- safety / compliance ---
ERR_MERCHANT_MISREPRESENTED = "ERR_MERCHANT_MISREPRESENTED"
ERR_MERCHANT_UNDER_CATEGORY_REVIEW = "ERR_MERCHANT_UNDER_CATEGORY_REVIEW"
ERR_MERCHANT_NOT_VERIFIED = "ERR_MERCHANT_NOT_VERIFIED"
ERR_ACQUIRER_NON_COMPLIANT = "ERR_ACQUIRER_NON_COMPLIANT"

# --- temporal ---
ERR_CLEARING_BEFORE_AUTH = "ERR_CLEARING_BEFORE_AUTH"
ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS = "ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS"

# --- constraint ---
ERR_RATE_VERSION_WINDOW_OVERLAP = "ERR_RATE_VERSION_WINDOW_OVERLAP"
ERR_PLATFORM_WINDOW_CONFLICT = "ERR_PLATFORM_WINDOW_CONFLICT"
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"
ERR_REVIEW_ROUND_LIMIT_EXCEEDED = "ERR_REVIEW_ROUND_LIMIT_EXCEEDED"
ERR_DUPLICATE_ENROLLMENT = "ERR_DUPLICATE_ENROLLMENT"

# --- referential / eligibility ---
ERR_MCC_NOT_DEFINED = "ERR_MCC_NOT_DEFINED"
ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM = "ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM"
ERR_NO_QUALIFYING_RATE_PROGRAM = "ERR_NO_QUALIFYING_RATE_PROGRAM"
ERR_FX_RATE_UNAVAILABLE = "ERR_FX_RATE_UNAVAILABLE"
ERR_DOCUMENTATION_REQUIRED = "ERR_DOCUMENTATION_REQUIRED"

# --- fiscal ---
ERR_COMMITMENT_BELOW_MINIMUM = "ERR_COMMITMENT_BELOW_MINIMUM"
ERR_INCENTIVE_CAPACITY_EXCEEDED = "ERR_INCENTIVE_CAPACITY_EXCEEDED"


HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_ACQUIRER_SCOPE_VIOLATION: 403,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_PLATFORM_NOT_FOUND: 404,
    ERR_ACQUIRER_NOT_FOUND: 404,
    ERR_MCC_DEFINITION_NOT_FOUND: 404,
    ERR_MERCHANT_NOT_FOUND: 404,
    ERR_RATE_PROGRAM_NOT_FOUND: 404,
    ERR_RATE_VERSION_NOT_FOUND: 404,
    ERR_WINDOW_NOT_FOUND: 404,
    ERR_BATCH_NOT_FOUND: 404,
    ERR_RECORD_NOT_FOUND: 404,
    ERR_RECLASS_REQUEST_NOT_FOUND: 404,
    ERR_INCENTIVE_PROGRAM_NOT_FOUND: 404,
    ERR_ENROLLMENT_NOT_FOUND: 404,
    ERR_AUDIT_NOT_FOUND: 404,
    ERR_FX_RATE_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_INVALID_STATE: 409,
    ERR_BATCH_NOT_OPEN: 409,
    ERR_ENROLLMENT_CLOSED: 409,
    ERR_STALE_VERSION: 412,
    ERR_MERCHANT_MISREPRESENTED: 409,
    ERR_MERCHANT_UNDER_CATEGORY_REVIEW: 409,
    ERR_MERCHANT_NOT_VERIFIED: 409,
    ERR_ACQUIRER_NON_COMPLIANT: 409,
    ERR_CLEARING_BEFORE_AUTH: 422,
    ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS: 422,
    ERR_RATE_VERSION_WINDOW_OVERLAP: 409,
    ERR_PLATFORM_WINDOW_CONFLICT: 409,
    ERR_DUPLICATE_RESOURCE: 409,
    ERR_REVIEW_ROUND_LIMIT_EXCEEDED: 422,
    ERR_DUPLICATE_ENROLLMENT: 409,
    ERR_MCC_NOT_DEFINED: 422,
    ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM: 422,
    ERR_NO_QUALIFYING_RATE_PROGRAM: 422,
    ERR_FX_RATE_UNAVAILABLE: 422,
    ERR_DOCUMENTATION_REQUIRED: 422,
    ERR_COMMITMENT_BELOW_MINIMUM: 422,
    ERR_INCENTIVE_CAPACITY_EXCEEDED: 409,
}

DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "Missing or invalid authentication headers.",
    ERR_UNAUTHORIZED: "The acting role is not authorized for this endpoint.",
    ERR_ACQUIRER_SCOPE_VIOLATION: "The acting acquirer does not own the target resource.",
    ERR_SEGREGATION_OF_DUTIES: "Segregation of duties forbids this operator from acting here.",
    ERR_INVALID_REQUEST: "The request body or query string is malformed.",
    ERR_INVALID_STATE: "The target resource's status does not permit this transition.",
    ERR_BATCH_NOT_OPEN: "The settlement batch is not OPEN.",
    ERR_ENROLLMENT_CLOSED: "The incentive program is CLOSED_FULL.",
    ERR_STALE_VERSION: "The supplied expected version does not match the stored version.",
    ERR_MERCHANT_MISREPRESENTED: "The merchant is in the terminal MISREPRESENTED state.",
    ERR_MERCHANT_UNDER_CATEGORY_REVIEW: "The merchant is UNDER_REVIEW by a category audit.",
    ERR_MERCHANT_NOT_VERIFIED: "The merchant's category is not VERIFIED.",
    ERR_ACQUIRER_NON_COMPLIANT: "The owning acquirer is NON_COMPLIANT.",
    ERR_CLEARING_BEFORE_AUTH: "clearing_timestamp precedes auth_timestamp.",
    ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS: "The window falls outside the version's publication-to-deadline envelope.",
    ERR_RATE_VERSION_WINDOW_OVERLAP: "The version's effective interval overlaps another PUBLISHED version.",
    ERR_PLATFORM_WINDOW_CONFLICT: "The platform has no free concurrent-window capacity for this interval.",
    ERR_DUPLICATE_RESOURCE: "A resource with the same natural key already exists.",
    ERR_REVIEW_ROUND_LIMIT_EXCEEDED: "The review-round ceiling has been reached.",
    ERR_DUPLICATE_ENROLLMENT: "The merchant already holds a live enrollment on this program.",
    ERR_MCC_NOT_DEFINED: "No merchant category definition matches.",
    ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM: "The merchant's assigned MCC is not eligible for the program.",
    ERR_NO_QUALIFYING_RATE_PROGRAM: "No rate program is selectable for this record.",
    ERR_FX_RATE_UNAVAILABLE: "No effective currency-conversion row exists for the pair.",
    ERR_DOCUMENTATION_REQUIRED: "A non-empty documentation reference is required.",
    ERR_COMMITMENT_BELOW_MINIMUM: "committed_volume_cents is below the program minimum.",
    ERR_INCENTIVE_CAPACITY_EXCEEDED: "committed_volume_cents exceeds the program's uncommitted capacity.",
    ERR_PLATFORM_NOT_FOUND: "No ProcessingPlatform with the supplied id.",
    ERR_ACQUIRER_NOT_FOUND: "No Acquirer with the supplied id.",
    ERR_MCC_DEFINITION_NOT_FOUND: "No MccDefinition with the supplied id.",
    ERR_MERCHANT_NOT_FOUND: "No Merchant with the supplied id.",
    ERR_RATE_PROGRAM_NOT_FOUND: "No RateProgram with the supplied id.",
    ERR_RATE_VERSION_NOT_FOUND: "No RateProgramVersion with the supplied id.",
    ERR_WINDOW_NOT_FOUND: "No AcquirerImplementationWindow with the supplied id.",
    ERR_BATCH_NOT_FOUND: "No SettlementBatch with the supplied id.",
    ERR_RECORD_NOT_FOUND: "No TransactionRecord with the supplied id.",
    ERR_RECLASS_REQUEST_NOT_FOUND: "No ReclassificationRequest with the supplied id.",
    ERR_INCENTIVE_PROGRAM_NOT_FOUND: "No IncentiveProgram with the supplied id.",
    ERR_ENROLLMENT_NOT_FOUND: "No IncentiveEnrollment with the supplied id.",
    ERR_AUDIT_NOT_FOUND: "No MerchantCategoryAudit with the supplied id.",
    ERR_FX_RATE_NOT_FOUND: "No FxRate with the supplied id.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, HTTP_STATUS[error_id], message)

"""Error catalogue (PRD section 5) and the raised exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_RECORD_FROZEN = "ERR_RECORD_FROZEN"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_PATIENT_VERSION = "ERR_STALE_PATIENT_VERSION"
ERR_STALE_CARE_PLAN_VERSION = "ERR_STALE_CARE_PLAN_VERSION"
ERR_STALE_ELECTION_VERSION = "ERR_STALE_ELECTION_VERSION"
ERR_REFERRAL_INELIGIBLE = "ERR_REFERRAL_INELIGIBLE"
ERR_REREFERRAL_LIMIT = "ERR_REREFERRAL_LIMIT"
ERR_WITNESS_CONFLICT = "ERR_WITNESS_CONFLICT"
ERR_EXECUTION_REQUIREMENT_UNMET = "ERR_EXECUTION_REQUIREMENT_UNMET"
ERR_SIGNATURE_INCOMPLETE = "ERR_SIGNATURE_INCOMPLETE"
ERR_CODE_STATUS_LADDER_VIOLATION = "ERR_CODE_STATUS_LADDER_VIOLATION"
ERR_GOALS_CONFLICT = "ERR_GOALS_CONFLICT"
ERR_SURROGATE_HIERARCHY_EMPTY = "ERR_SURROGATE_HIERARCHY_EMPTY"
ERR_NOT_AUTHORIZED_DECISION_MAKER = "ERR_NOT_AUTHORIZED_DECISION_MAKER"
ERR_QUORUM_NOT_MET = "ERR_QUORUM_NOT_MET"
ERR_ATTESTATION_WINDOW_EXPIRED = "ERR_ATTESTATION_WINDOW_EXPIRED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_DUPLICATE_CERTIFIER = "ERR_DUPLICATE_CERTIFIER"
ERR_MME_REVIEW_REQUIRED = "ERR_MME_REVIEW_REQUIRED"
ERR_EARLY_REFILL = "ERR_EARLY_REFILL"
ERR_SCHEDULE_CONFLICT = "ERR_SCHEDULE_CONFLICT"
ERR_PRIOR_AUTH_REQUIRED = "ERR_PRIOR_AUTH_REQUIRED"
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"
ERR_IDT_CADENCE_LAPSED = "ERR_IDT_CADENCE_LAPSED"
ERR_FACE_TO_FACE_WINDOW = "ERR_FACE_TO_FACE_WINDOW"
ERR_INSUFFICIENT_DOCUMENTED_TIME = "ERR_INSUFFICIENT_DOCUMENTED_TIME"
ERR_CONCURRENT_CARE_OVERLAP = "ERR_CONCURRENT_CARE_OVERLAP"
ERR_ATTESTATION_REQUIRED = "ERR_ATTESTATION_REQUIRED"

HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_RESOURCE_NOT_FOUND: 404,
    ERR_VALIDATION: 400,
    ERR_RECORD_FROZEN: 409,
    ERR_INVALID_STATE: 409,
    ERR_STALE_PATIENT_VERSION: 412,
    ERR_STALE_CARE_PLAN_VERSION: 412,
    ERR_STALE_ELECTION_VERSION: 412,
    ERR_REFERRAL_INELIGIBLE: 422,
    ERR_REREFERRAL_LIMIT: 409,
    ERR_WITNESS_CONFLICT: 422,
    ERR_EXECUTION_REQUIREMENT_UNMET: 422,
    ERR_SIGNATURE_INCOMPLETE: 422,
    ERR_CODE_STATUS_LADDER_VIOLATION: 422,
    ERR_GOALS_CONFLICT: 409,
    ERR_SURROGATE_HIERARCHY_EMPTY: 422,
    ERR_NOT_AUTHORIZED_DECISION_MAKER: 422,
    ERR_QUORUM_NOT_MET: 422,
    ERR_ATTESTATION_WINDOW_EXPIRED: 422,
    ERR_SEGREGATION_OF_DUTIES: 422,
    ERR_DUPLICATE_CERTIFIER: 422,
    ERR_MME_REVIEW_REQUIRED: 422,
    ERR_EARLY_REFILL: 422,
    ERR_SCHEDULE_CONFLICT: 409,
    ERR_PRIOR_AUTH_REQUIRED: 422,
    ERR_INSUFFICIENT_INVENTORY: 409,
    ERR_IDT_CADENCE_LAPSED: 422,
    ERR_FACE_TO_FACE_WINDOW: 422,
    ERR_INSUFFICIENT_DOCUMENTED_TIME: 422,
    ERR_CONCURRENT_CARE_OVERLAP: 409,
    ERR_ATTESTATION_REQUIRED: 422,
}

_DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "Authentication headers are missing or invalid.",
    ERR_UNAUTHORIZED: "The acting role is not authorised for this endpoint.",
    ERR_RESOURCE_NOT_FOUND: "The referenced resource does not exist.",
    ERR_VALIDATION: "The request body failed validation.",
    ERR_RECORD_FROZEN: "The patient's records are frozen.",
    ERR_INVALID_STATE: "The target row is not in a state that permits this transition.",
    ERR_STALE_PATIENT_VERSION: "expected_patient_version does not match the patient's current version.",
    ERR_STALE_CARE_PLAN_VERSION: "expected_care_plan_version does not match the plan's current version.",
    ERR_STALE_ELECTION_VERSION: "expected_election_version does not match the election's current version.",
    ERR_REFERRAL_INELIGIBLE: "The referral's triage score is below the acceptance floor.",
    ERR_REREFERRAL_LIMIT: "The re-referral cap has been reached.",
    ERR_WITNESS_CONFLICT: "The signer may not witness this document.",
    ERR_EXECUTION_REQUIREMENT_UNMET: "The jurisdiction execution requirement is unmet.",
    ERR_SIGNATURE_INCOMPLETE: "The POLST signature requirement is unmet.",
    ERR_CODE_STATUS_LADDER_VIOLATION: "The requested code status violates the ladder rule.",
    ERR_GOALS_CONFLICT: "A conflict resolution note is required.",
    ERR_SURROGATE_HIERARCHY_EMPTY: "No active surrogate designation is available.",
    ERR_NOT_AUTHORIZED_DECISION_MAKER: "The named decision maker is not authorised.",
    ERR_QUORUM_NOT_MET: "The conference did not record a successful quorum.",
    ERR_ATTESTATION_WINDOW_EXPIRED: "The attestation window has expired.",
    ERR_SEGREGATION_OF_DUTIES: "Segregation of duties prevents this action.",
    ERR_DUPLICATE_CERTIFIER: "The second certification must come from a different user.",
    ERR_MME_REVIEW_REQUIRED: "A physician MME review is required before a refill.",
    ERR_EARLY_REFILL: "The refill window has not opened yet.",
    ERR_SCHEDULE_CONFLICT: "The requested interval conflicts with an existing booking.",
    ERR_PRIOR_AUTH_REQUIRED: "Prior authorisation is required before scheduling.",
    ERR_INSUFFICIENT_INVENTORY: "Insufficient inventory units are available.",
    ERR_IDT_CADENCE_LAPSED: "The interdisciplinary cadence has lapsed.",
    ERR_FACE_TO_FACE_WINDOW: "The face-to-face encounter is outside its permitted window.",
    ERR_INSUFFICIENT_DOCUMENTED_TIME: "The claim's documented minutes are below the billable minimum.",
    ERR_CONCURRENT_CARE_OVERLAP: "The service date falls inside an elected hospice benefit period.",
    ERR_ATTESTATION_REQUIRED: "The supporting conference documentation is not complete.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, HTTP_STATUS[error_id], message)

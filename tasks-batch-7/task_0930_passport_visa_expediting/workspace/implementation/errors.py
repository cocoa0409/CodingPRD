"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_NOT_ORDER_MEMBER": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_AGENCY_CUSTODY_LOCK": 409,
    "ERR_ORDER_TERMINAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NATIONALITY_MISMATCH": 422,
    "ERR_CUSTODY_MISMATCH": 409,
    "ERR_LEG_SEQUENCE_VIOLATION": 409,
    "ERR_EMBASSY_CLOSED": 409,
    "ERR_OUT_OF_JURISDICTION": 422,
    "ERR_LEAD_TIME_VIOLATION": 422,
    "ERR_SLOT_CAPACITY_EXCEEDED": 409,
    "ERR_RESCHEDULE_CAP_EXCEEDED": 409,
    "ERR_RESUBMISSION_CAP_EXCEEDED": 409,
    "ERR_DOCUMENT_VALIDITY_INSUFFICIENT": 422,
    "ERR_PHOTO_RETAKE_CAP_EXCEEDED": 409,
    "ERR_FORM_REVISION_STALE": 409,
    "ERR_COURIER_ATTEMPT_CAP_EXCEEDED": 409,
    "ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED": 409,
    "ERR_RFE_ROUND_CAP_EXCEEDED": 409,
    "ERR_RFE_DEADLINE_PASSED": 409,
    "ERR_TIER_NOT_AN_UPGRADE": 422,
    "ERR_UPGRADE_STAGE_CLOSED": 409,
    "ERR_STREAM_ALLOCATION_INVALID": 422,
    "ERR_APPLICANT_NOT_READY": 409,
    "ERR_SPLIT_PARTITION_MISMATCH": 422,
    "ERR_REQUIRED_DOCUMENTS_INCOMPLETE": 409,
    "ERR_RUSH_CUTOFF_MISSED": 409,
    "ERR_TRAVEL_DATE_INFEASIBLE": 409,
    "ERR_BALANCE_OUTSTANDING": 402,
    "ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED": 422,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_UNAUTHORIZED": "The acting role may not call this endpoint.",
    "ERR_ORDER_NOT_FOUND": "The referenced order does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_NOT_ORDER_MEMBER": "The traveller is not a member of the targeted order.",
    "ERR_VALIDATION": "The request payload failed validation.",
    "ERR_INVALID_ENUM": "An enum-typed request field carries an undeclared member.",
    "ERR_AGENCY_CUSTODY_LOCK": "The passport is in agency custody; this write is refused.",
    "ERR_ORDER_TERMINAL": "The order is in a terminal workflow status.",
    "ERR_INVALID_STATE": "The resource is not in a state admitting this transition.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_SEGREGATION_OF_DUTIES": "The submitting user produced the standing quote.",
    "ERR_NATIONALITY_MISMATCH": "The applicant nationality differs from the catalog item.",
    "ERR_CUSTODY_MISMATCH": "The passport is not with the required holder.",
    "ERR_LEG_SEQUENCE_VIOLATION": "The courier leg is dispatched out of leg_index order.",
    "ERR_EMBASSY_CLOSED": "The date is not a business day or falls on a consulate closure.",
    "ERR_OUT_OF_JURISDICTION": "The applicant residence region is outside the mission jurisdiction.",
    "ERR_LEAD_TIME_VIOLATION": "The slot starts inside the appointment lead-time window.",
    "ERR_SLOT_CAPACITY_EXCEEDED": "The target slot has no remaining capacity.",
    "ERR_RESCHEDULE_CAP_EXCEEDED": "The reschedule or rebook cap has been reached.",
    "ERR_RESUBMISSION_CAP_EXCEEDED": "The document resubmission cap has been reached.",
    "ERR_DOCUMENT_VALIDITY_INSUFFICIENT": "The document fails its validity window.",
    "ERR_PHOTO_RETAKE_CAP_EXCEEDED": "The photo retake cap has been reached.",
    "ERR_FORM_REVISION_STALE": "The named agency form revision is not the active product revision.",
    "ERR_COURIER_ATTEMPT_CAP_EXCEEDED": "The courier dispatch attempt cap has been reached.",
    "ERR_DELIVERY_ATTEMPT_CAP_EXCEEDED": "The delivery attempt cap has been reached.",
    "ERR_RFE_ROUND_CAP_EXCEEDED": "The evidence-request round cap has been reached.",
    "ERR_RFE_DEADLINE_PASSED": "The evidence-request deadline has passed.",
    "ERR_TIER_NOT_AN_UPGRADE": "The requested service level is not strictly higher.",
    "ERR_UPGRADE_STAGE_CLOSED": "A tier change is closed at this workflow stage.",
    "ERR_STREAM_ALLOCATION_INVALID": "The stream override would overfill the government bucket.",
    "ERR_APPLICANT_NOT_READY": "A named applicant is not eligible for the split.",
    "ERR_SPLIT_PARTITION_MISMATCH": "transfer_cents_override differs from the computed transfer.",
    "ERR_REQUIRED_DOCUMENTS_INCOMPLETE": "Some traveller on the order is not yet complete.",
    "ERR_RUSH_CUTOFF_MISSED": "The RUSH submission cutoff has passed.",
    "ERR_TRAVEL_DATE_INFEASIBLE": "The projected completion date is infeasible.",
    "ERR_BALANCE_OUTSTANDING": "The held customer money does not cover the quoted total.",
    "ERR_GOVERNMENT_FEE_FORFEIT_UNACKNOWLEDGED": "The government fee forfeit was not acknowledged.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, ERROR_HTTP[error_id], message)

"""Error catalogue for the Transitional Care & Readmission Program API.

Every entry mirrors PRD section 5 verbatim.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_EPISODE_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_ENTITY_LINK_MISMATCH": 409,
    "ERR_NOT_EPISODE_OWNER": 403,
    "ERR_EPISODE_RECORDS_FROZEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DISPOSITION_INELIGIBLE": 422,
    "ERR_INTAKE_WINDOW_EXPIRED": 422,
    "ERR_EPISODE_ALREADY_OPEN": 409,
    "ERR_PAYER_NOT_COVERED": 422,
    "ERR_FACILITY_OUT_OF_NETWORK": 422,
    "ERR_CONTACT_ATTEMPT_LIMIT": 422,
    "ERR_SCHEDULE_CONFLICT": 409,
    "ERR_MODALITY_OUT_OF_SEQUENCE": 422,
    "ERR_BLOCKING_BARRIER_OPEN": 422,
    "ERR_MEDREC_NOT_COMPLETE": 422,
    "ERR_BLOCKING_DISCREPANCY_UNRESOLVED": 422,
    "ERR_DEFERRAL_NOT_PERMITTED": 422,
    "ERR_REQUIRED_ELEMENTS_INCOMPLETE": 422,
    "ERR_SERVICE_PERIOD_OPEN": 422,
    "ERR_READMISSION_OUT_OF_WINDOW": 422,
    "ERR_CLAIM_NOT_BILLABLE": 422,
    "ERR_VISIT_WINDOW_MISSED": 422,
    "ERR_CONTACT_NOT_TIMELY": 422,
    "ERR_DUPLICATE_TCM_CLAIM": 409,
    "ERR_APPEAL_LIMIT_REACHED": 422,
    "ERR_HANDOFF_EXPIRED": 409,
    "ERR_NAVIGATOR_CAP_EXCEEDED": 409,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this operation.",
    "ERR_VALIDATION": "The request body failed validation.",
    "ERR_INVALID_ENUM": "An enum-typed body field carries a value outside its declared members.",
    "ERR_EPISODE_NOT_FOUND": "The care episode does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_ENTITY_LINK_MISMATCH": "The supplied reference does not belong to the parent named in the path.",
    "ERR_NOT_EPISODE_OWNER": "The acting navigator does not own this care episode.",
    "ERR_EPISODE_RECORDS_FROZEN": "The care episode's records are frozen.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition is declared.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this operation.",
    "ERR_DISPOSITION_INELIGIBLE": "The referral's discharge disposition is not programme-eligible.",
    "ERR_INTAKE_WINDOW_EXPIRED": "The referral was recorded outside the intake window.",
    "ERR_EPISODE_ALREADY_OPEN": "The patient already has an open care episode.",
    "ERR_PAYER_NOT_COVERED": "The payer does not reimburse the TCM codes.",
    "ERR_FACILITY_OUT_OF_NETWORK": "The discharging facility is out of network.",
    "ERR_CONTACT_ATTEMPT_LIMIT": "The episode has already used its four contact attempts.",
    "ERR_SCHEDULE_CONFLICT": "The requested interval collides with an existing commitment.",
    "ERR_MODALITY_OUT_OF_SEQUENCE": "The supplied modality does not match the ladder position.",
    "ERR_BLOCKING_BARRIER_OPEN": "A blocking-class barrier on the episode is still open.",
    "ERR_MEDREC_NOT_COMPLETE": "The episode's medication reconciliation is not complete.",
    "ERR_BLOCKING_DISCREPANCY_UNRESOLVED": "A HIGH or CRITICAL discrepancy is still unresolved.",
    "ERR_DEFERRAL_NOT_PERMITTED": "Only LOW and MODERATE discrepancies may be deferred.",
    "ERR_REQUIRED_ELEMENTS_INCOMPLETE": "The documented elements are missing a required member.",
    "ERR_SERVICE_PERIOD_OPEN": "The service period is still open.",
    "ERR_READMISSION_OUT_OF_WINDOW": "The readmission falls outside the thirty-day window.",
    "ERR_CLAIM_NOT_BILLABLE": "The episode has no completed and attested visit to bill.",
    "ERR_VISIT_WINDOW_MISSED": "The visit happened after the last billable day.",
    "ERR_CONTACT_NOT_TIMELY": "The interactive contact was not timely.",
    "ERR_DUPLICATE_TCM_CLAIM": "Another non-voided claim covers an overlapping service period.",
    "ERR_APPEAL_LIMIT_REACHED": "The appeal bound has been exhausted.",
    "ERR_HANDOFF_EXPIRED": "The handoff proposal has expired.",
    "ERR_NAVIGATOR_CAP_EXCEEDED": "The receiving navigator's workload cap would be exceeded.",
}

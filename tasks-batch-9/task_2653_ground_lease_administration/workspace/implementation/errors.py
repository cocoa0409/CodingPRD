"""Error catalogue for the Ground Lease Administration API (PRD section 5)."""


class ApiError(Exception):
    """Carries the error_id, the HTTP status and a human readable message."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    # --- not found ---
    "ERR_LESSEE_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_MORTGAGE_NOT_FOUND": 404,
    "ERR_REVALUATION_NOT_FOUND": 404,
    "ERR_APPRAISAL_NOT_FOUND": 404,
    "ERR_ARBITRATION_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_ALTERATION_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_LOSS_EVENT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    # --- authorisation ---
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_APPRAISAL_SIDE_MISMATCH": 403,
    # --- format and concurrency ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_LEASE_VERSION": 412,
    "ERR_DUPLICATE_RECORD": 409,
    # --- state ---
    "ERR_INVALID_STATE": 409,
    "ERR_LEASE_NOT_OPERATIVE": 409,
    "ERR_CROSS_ENTITY_BLOCKED": 409,
    "ERR_APPRAISALS_INCOMPLETE": 409,
    "ERR_MAX_ROUNDS_REACHED": 409,
    "ERR_DIVERGENCE_BELOW_THRESHOLD": 409,
    "ERR_ELECTION_NOT_AVAILABLE": 409,
    "ERR_STANDARD_MET_NO_HOLDBACK": 409,
    "ERR_INTERVAL_OVERLAP": 409,
    "ERR_CURE_WINDOW_CLOSED": 409,
    "ERR_GFA_ENVELOPE_EXCEEDED": 409,
    "ERR_SUBLET_AREA_EXCEEDED": 409,
    "ERR_INSURANCE_DEFICIENT": 409,
    # --- temporal / financial / business ---
    "ERR_CHRONOLOGY_VIOLATION": 422,
    "ERR_AMOUNT_NOT_RECONCILED": 422,
    "ERR_TERMS_INCOHERENT": 422,
    "ERR_USE_NOT_PERMITTED": 422,
    "ERR_CREDIT_RATING_REFUSED": 422,
    "ERR_MORTGAGE_LEASE_MISMATCH": 422,
    "ERR_TRANSFER_FIELDS_MISMATCHED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_LESSEE_NOT_FOUND": "The referenced lessee does not exist.",
    "ERR_LEASE_NOT_FOUND": "The referenced lease does not exist.",
    "ERR_MORTGAGE_NOT_FOUND": "The referenced leasehold mortgage does not exist.",
    "ERR_REVALUATION_NOT_FOUND": "The referenced rent revaluation does not exist.",
    "ERR_APPRAISAL_NOT_FOUND": "The referenced appraisal submission does not exist.",
    "ERR_ARBITRATION_NOT_FOUND": "The referenced arbitration proceeding does not exist.",
    "ERR_STATEMENT_NOT_FOUND": "The referenced percentage-rent statement does not exist.",
    "ERR_ALTERATION_NOT_FOUND": "The referenced alteration request does not exist.",
    "ERR_TRANSFER_NOT_FOUND": "The referenced transfer request does not exist.",
    "ERR_NOTICE_NOT_FOUND": "The referenced default notice does not exist.",
    "ERR_LOSS_EVENT_NOT_FOUND": "The referenced loss event does not exist.",
    "ERR_ASSESSMENT_NOT_FOUND": "The referenced reversion assessment does not exist.",
    "ERR_CERTIFICATE_NOT_FOUND": "The referenced estoppel certificate does not exist.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties bars this user from this operation.",
    "ERR_APPRAISAL_SIDE_MISMATCH": "The acting role may not lodge an appraisal for that side.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_STALE_LEASE_VERSION": "The pinned lease version is stale.",
    "ERR_DUPLICATE_RECORD": "A conflicting record already exists.",
    "ERR_INVALID_STATE": "The resource is not in a state that permits this operation.",
    "ERR_LEASE_NOT_OPERATIVE": "The lease is no longer operative.",
    "ERR_CROSS_ENTITY_BLOCKED": "Another resource on the lease blocks this operation.",
    "ERR_APPRAISALS_INCOMPLETE": "Both party appraisals are required for the current round.",
    "ERR_MAX_ROUNDS_REACHED": "The maximum number of negotiation rounds has been reached.",
    "ERR_DIVERGENCE_BELOW_THRESHOLD": "The divergence does not exceed the arbitration threshold.",
    "ERR_ELECTION_NOT_AVAILABLE": "The requested election is not available on this loss event.",
    "ERR_STANDARD_MET_NO_HOLDBACK": "The condition standard was met; no holdback may be applied.",
    "ERR_INTERVAL_OVERLAP": "The proposed interval overlaps an existing one.",
    "ERR_CURE_WINDOW_CLOSED": "The applicable window has closed.",
    "ERR_GFA_ENVELOPE_EXCEEDED": "The development envelope cannot accommodate the work.",
    "ERR_SUBLET_AREA_EXCEEDED": "The sublet area would exceed the development envelope.",
    "ERR_INSURANCE_DEFICIENT": "The insurance on file is deficient for this operation.",
    "ERR_CHRONOLOGY_VIOLATION": "The supplied instants violate the chronology rules.",
    "ERR_AMOUNT_NOT_RECONCILED": "The supplied amount does not reconcile.",
    "ERR_TERMS_INCOHERENT": "The lease terms are incoherent.",
    "ERR_USE_NOT_PERMITTED": "The proposed use is not the use permitted by the lease.",
    "ERR_CREDIT_RATING_REFUSED": "The transferee credit rating is refused consent.",
    "ERR_MORTGAGE_LEASE_MISMATCH": "The named mortgage does not encumber that lease.",
    "ERR_TRANSFER_FIELDS_MISMATCHED": "The transfer type requires fields that were omitted.",
}

"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or STATUS.get(error_id, 400)
        self.message = message or MESSAGES.get(error_id, error_id)


STATUS = {
    # ---- authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ACTION_NOT_PERMITTED_FOR_ROLE": 403,
    "ERR_PARTICIPANT_SCOPE_VIOLATION": 403,
    "ERR_PURPOSE_NOT_PERMITTED_FOR_ROLE": 403,
    "ERR_SOD_CERTIFIER_IS_SIGNATORY": 403,
    "ERR_SOD_STEWARD_IS_TUNER": 403,
    "ERR_REVIEW_NOT_CLAIMED_BY_ACTOR": 403,
    # ---- schema
    "ERR_INVALID_REQUEST": 400,
    # ---- existence
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_CONFORMANCE_TEST_NOT_FOUND": 404,
    "ERR_CONSENT_POLICY_NOT_FOUND": 404,
    "ERR_THRESHOLD_CONFIG_NOT_FOUND": 404,
    "ERR_PATIENT_RECORD_NOT_FOUND": 404,
    "ERR_CLUSTER_NOT_FOUND": 404,
    "ERR_MATCH_LINK_NOT_FOUND": 404,
    "ERR_DIRECTIVE_NOT_FOUND": 404,
    "ERR_QUERY_NOT_FOUND": 404,
    "ERR_AUDIT_ENTRY_NOT_FOUND": 404,
    "ERR_BREAK_GLASS_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_DATA_FEED_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    # ---- optimistic concurrency
    "ERR_STALE_CLUSTER_VERSION": 412,
    "ERR_STALE_PARTICIPANT_VERSION": 412,
    # ---- state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_TERMINAL_STATE": 409,
    "ERR_PARTICIPANT_NOT_CERTIFIED": 409,
    "ERR_PARTICIPANT_NOT_ONBOARDED_FOR_DATA": 409,
    "ERR_CERTIFICATION_PROFILES_INCOMPLETE": 409,
    "ERR_CONFORMANCE_PROFILE_ALREADY_PASSED": 409,
    "ERR_QUERY_FEED_NOT_OPERATIONAL": 409,
    "ERR_CLUSTER_MERGED_AWAY": 409,
    "ERR_NO_ACTIVE_CONSENT_POLICY": 409,
    "ERR_NO_ACTIVE_THRESHOLD_CONFIG": 409,
    "ERR_SUBSCRIPTION_CONFORMANCE_MISSING": 409,
    "ERR_BREAK_GLASS_SESSION_NOT_OPEN": 409,
    "ERR_BREAK_GLASS_COOLDOWN_ACTIVE": 409,
    "ERR_CONSENT_POLICY_INTERVAL_OVERLAP": 409,
    "ERR_DUPLICATE_SOURCE_MRN": 409,
    "ERR_INVOICE_PERIOD_OVERLAP": 409,
    "ERR_NO_RECONCILIATION_BASIS": 409,
    # ---- payment
    "ERR_PARTICIPATION_FEE_DELINQUENT": 402,
    # ---- semantic / unprocessable
    "ERR_CONDUIT_ORG_TYPE_INVALID": 422,
    "ERR_SUBSCRIPTION_SCOPE_MISMATCH": 422,
    "ERR_DIRECTIVE_SCOPE_PARTICIPANT_REQUIRED": 422,
    "ERR_JUSTIFICATION_TOO_SHORT": 422,
    "ERR_QUALITY_SAMPLE_INVALID": 422,
    "ERR_THRESHOLD_CONFIG_INVALID": 422,
    "ERR_INVOICE_PERIOD_NOT_ELAPSED": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}

MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role header is absent or empty.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not call this endpoint.",
    "ERR_ACTION_NOT_PERMITTED_FOR_ROLE": "The acting role may not perform this action.",
    "ERR_PARTICIPANT_SCOPE_VIOLATION": "The acting user may only operate inside its own participant.",
    "ERR_PURPOSE_NOT_PERMITTED_FOR_ROLE": "The purpose of use is not permitted for this role.",
    "ERR_SOD_CERTIFIER_IS_SIGNATORY": "The certifying administrator executed the agreement.",
    "ERR_SOD_STEWARD_IS_TUNER": "The deciding steward activated the pinned threshold generation.",
    "ERR_REVIEW_NOT_CLAIMED_BY_ACTOR": "The review is not claimed by the acting user.",
    "ERR_INVALID_REQUEST": "The request body or query string failed schema validation.",
    "ERR_PARTICIPANT_NOT_FOUND": "Participant not found.",
    "ERR_CONFORMANCE_TEST_NOT_FOUND": "Conformance test not found.",
    "ERR_CONSENT_POLICY_NOT_FOUND": "Consent policy not found.",
    "ERR_THRESHOLD_CONFIG_NOT_FOUND": "Match threshold configuration not found.",
    "ERR_PATIENT_RECORD_NOT_FOUND": "Patient record not found.",
    "ERR_CLUSTER_NOT_FOUND": "Identity cluster not found.",
    "ERR_MATCH_LINK_NOT_FOUND": "Match link not found.",
    "ERR_DIRECTIVE_NOT_FOUND": "Consent directive not found.",
    "ERR_QUERY_NOT_FOUND": "Record locator query not found.",
    "ERR_AUDIT_ENTRY_NOT_FOUND": "Access audit entry not found.",
    "ERR_BREAK_GLASS_NOT_FOUND": "Break-glass access not found.",
    "ERR_SUBSCRIPTION_NOT_FOUND": "Notification subscription not found.",
    "ERR_DATA_FEED_NOT_FOUND": "Data feed not found.",
    "ERR_INVOICE_NOT_FOUND": "Participation invoice not found.",
    "ERR_STALE_CLUSTER_VERSION": "expected_cluster_version does not match the stored cluster version.",
    "ERR_STALE_PARTICIPANT_VERSION": "expected_participant_version does not match the stored participant version.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not available from the current state.",
    "ERR_TERMINAL_STATE": "The resource is in a terminal state.",
    "ERR_PARTICIPANT_NOT_CERTIFIED": "The participant is not CERTIFIED.",
    "ERR_PARTICIPANT_NOT_ONBOARDED_FOR_DATA": "The participant has not progressed far enough to carry data.",
    "ERR_CERTIFICATION_PROFILES_INCOMPLETE": "The required certification profiles have not all passed.",
    "ERR_CONFORMANCE_PROFILE_ALREADY_PASSED": "That profile already has a PASSED run.",
    "ERR_QUERY_FEED_NOT_OPERATIONAL": "The querying participant has no operational CCDA feed.",
    "ERR_CLUSTER_MERGED_AWAY": "The identity cluster has been merged away.",
    "ERR_NO_ACTIVE_CONSENT_POLICY": "No consent policy governs the current logical clock.",
    "ERR_NO_ACTIVE_THRESHOLD_CONFIG": "No ACTIVE match threshold configuration exists.",
    "ERR_SUBSCRIPTION_CONFORMANCE_MISSING": "No PASSED ADT_PUBLISHER conformance run exists.",
    "ERR_BREAK_GLASS_SESSION_NOT_OPEN": "The break-glass session is not open for this operation.",
    "ERR_BREAK_GLASS_COOLDOWN_ACTIVE": "A prior break-glass session still occupies its cooldown window.",
    "ERR_CONSENT_POLICY_INTERVAL_OVERLAP": "The effective interval overlaps another policy.",
    "ERR_DUPLICATE_SOURCE_MRN": "source_mrn is already used by this participant.",
    "ERR_INVOICE_PERIOD_OVERLAP": "The billing period overlaps an existing invoice.",
    "ERR_NO_RECONCILIATION_BASIS": "No qualifying quality samples fall inside the billing period.",
    "ERR_PARTICIPATION_FEE_DELINQUENT": "The participant has a DELINQUENT participation invoice.",
    "ERR_CONDUIT_ORG_TYPE_INVALID": "PUBLIC_HEALTH_CONDUIT requires a PUBLIC_HEALTH organisation.",
    "ERR_SUBSCRIPTION_SCOPE_MISMATCH": "cluster_id does not agree with subscription_scope.",
    "ERR_DIRECTIVE_SCOPE_PARTICIPANT_REQUIRED": "The directive scope and payload are incoherent.",
    "ERR_JUSTIFICATION_TOO_SHORT": "The supplied narrative is shorter than forty characters.",
    "ERR_QUALITY_SAMPLE_INVALID": "The quality sample is internally inconsistent or overlaps another.",
    "ERR_THRESHOLD_CONFIG_INVALID": "The threshold configuration is not admissible.",
    "ERR_INVOICE_PERIOD_NOT_ELAPSED": "The billing period has not fully elapsed.",
    "ERR_PAYMENT_AMOUNT_MISMATCH": "The tendered amount does not settle the invoice exactly.",
}


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)

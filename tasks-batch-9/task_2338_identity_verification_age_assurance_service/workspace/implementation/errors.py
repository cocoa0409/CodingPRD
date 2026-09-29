"""Error catalogue (PRD section 5 / scaffold `errors`)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status=None, message=None):
        super().__init__(error_id)
        catalogue = ERRORS.get(error_id, (400, "Request failed."))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else catalogue[0]
        self.message = message if message is not None else catalogue[1]


ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers missing or unrecognised."),
    "ERR_ROLE_NOT_PERMITTED": (403, "Role is not permitted to perform this operation."),
    "ERR_CLIENT_SCOPE_VIOLATION": (403, "Client integrator may only act on its own client resources."),
    "ERR_REVIEW_ASSIGNEE_MISMATCH": (403, "Only the assigned reviewer may decide this case."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same user may not perform both steps of this control."),
    "ERR_CLIENT_NOT_FOUND": (404, "Client not found."),
    "ERR_METHOD_PROFILE_NOT_FOUND": (404, "Method profile not found."),
    "ERR_POLICY_NOT_FOUND": (404, "Verification policy not found."),
    "ERR_SESSION_NOT_FOUND": (404, "Verification session not found."),
    "ERR_ATTEMPT_NOT_FOUND": (404, "Method attempt not found."),
    "ERR_PATHWAY_NOT_FOUND": (404, "Alternative pathway not found."),
    "ERR_REVIEW_CASE_NOT_FOUND": (404, "Manual review case not found."),
    "ERR_AUDIT_NOT_FOUND": (404, "Bias audit not found."),
    "ERR_NOT_FOUND": (404, "Resource not found."),
    "ERR_METHOD_NOT_ALLOWED": (405, "Method not allowed for this resource."),
    "ERR_INVALID_REQUEST": (422, "Request body failed schema validation."),
    "ERR_AGE_ACCURACY_UNDOCUMENTED": (422, "Age estimation accuracy is not documented for the resolved age band."),
    "ERR_SESSION_STATE_INVALID": (409, "Verification session state does not allow this operation."),
    "ERR_ATTEMPT_STATE_INVALID": (409, "Method attempt state does not allow this operation."),
    "ERR_POLICY_STATE_INVALID": (409, "Verification policy state does not allow this operation."),
    "ERR_PATHWAY_STATE_INVALID": (409, "Alternative pathway state does not allow this operation."),
    "ERR_REVIEW_CASE_STATE_INVALID": (409, "Manual review case state does not allow this operation."),
    "ERR_AUDIT_STATE_INVALID": (409, "Bias audit state does not allow this operation."),
    "ERR_STALE_CLIENT_VERSION": (412, "Client version is stale; re-read the client and retry."),
    "ERR_STALE_METHOD_PROFILE_VERSION": (412, "Method profile version is stale; re-read the profile and retry."),
    "ERR_CLIENT_NOT_LIVE": (409, "Client integration state does not allow this operation."),
    "ERR_PINNED_POLICY_RETIRED": (409, "The policy pinned to this session has been retired."),
    "ERR_METHOD_RESTRICTED_BY_BIAS": (409, "Method profile is restricted pending bias remediation."),
    "ERR_MINOR_BIOMETRIC_PROHIBITED": (409, "Biometric processing is prohibited for this age band."),
    "ERR_BIOMETRIC_CONSENT_REQUIRED": (409, "Explicit biometric consent is required."),
    "ERR_NO_PUBLISHED_POLICY": (409, "Client has no published verification policy."),
    "ERR_METHOD_NOT_IN_POLICY": (409, "Requested method is not admitted by the pinned policy."),
    "ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE": (409, "This method cannot be attempted directly."),
    "ERR_EVIDENCE_METHOD_MISMATCH": (409, "Evidence kind does not match the attempt method."),
    "ERR_EVIDENCE_ALREADY_SUBMITTED": (409, "Evidence has already been submitted for this attempt."),
    "ERR_METHOD_PROFILE_DUPLICATE": (409, "Method profile already exists for this vendor and method."),
    "ERR_POLICY_VERSION_DUPLICATE": (409, "Policy version already exists for this client."),
    "ERR_COHORT_DUPLICATE": (409, "Cohort has already been recorded for this audit."),
    "ERR_SESSION_EXPIRED": (409, "Verification session has lapsed."),
    "ERR_AUDIT_WINDOW_OVERLAP": (409, "Audit window overlaps an existing audit for this method profile."),
    "ERR_NO_ELIGIBLE_METHOD": (409, "No eligible verification method is available."),
    "ERR_STEP_UP_LIMIT_REACHED": (409, "Step-up budget for this session is exhausted."),
    "ERR_ATTEMPT_PENDING_FINALIZATION": (409, "All method attempts must be finalised before completion."),
    "ERR_PENDING_PATHWAY_BLOCKS_COMPLETION": (409, "A pending alternative pathway blocks completion."),
    "ERR_ALTERNATIVE_PATHWAY_DISABLED": (409, "Alternative pathways are disabled by the pinned policy."),
    "ERR_AGE_ASSURANCE_MISSING": (409, "Age assurance is required before completion."),
    "ERR_INSUFFICIENT_COHORT_COVERAGE": (409, "Not enough demographic cohorts to evaluate disparity."),
    "ERR_REVIEW_CAPACITY_EXHAUSTED": (409, "Manual review capacity is exhausted for this client."),
    "ERR_CLIENT_DAILY_QUOTA_EXCEEDED": (409, "Client session quota for the rolling window is exhausted."),
    "ERR_INTERNAL": (500, "Internal server error."),
}


def fail(error_id, message=None):
    raise ApiError(error_id, message=message)

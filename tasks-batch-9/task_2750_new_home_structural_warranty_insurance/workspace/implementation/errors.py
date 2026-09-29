"""Error catalogue and the ApiError exception.

Every identifier and HTTP status below is taken verbatim from PRD.md section 5
(Error Code Catalogue) and SCAFFOLD.yaml section 1.6.
"""

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_BUILDER_PRINCIPAL": 403,
    "ERR_NOT_POLICY_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_BUILDER_NOT_FOUND": 404,
    "ERR_HOMEOWNER_NOT_FOUND": 404,
    "ERR_NEUTRAL_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_COVERAGE_TERM_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_RESERVE_ENTRY_NOT_FOUND": 404,
    "ERR_ESCALATION_CASE_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_CLOCK_REGRESSION": 422,
    # optimistic concurrency
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    # state
    "ERR_INVALID_BUILDER_STATE": 409,
    "ERR_INVALID_POLICY_STATE": 409,
    "ERR_INVALID_PREMIUM_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_TRANSFER_STATE": 409,
    "ERR_INVALID_ESCALATION_STATE": 409,
    "ERR_INVALID_NEUTRAL_STATE": 409,
    "ERR_BUILDER_NOT_APPROVED": 409,
    "ERR_PREMIUM_NOT_PAID": 409,
    "ERR_ENROLLMENT_ON_HOLD": 409,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_COVERAGE_LIMIT_EXHAUSTED": 409,
    "ERR_NEUTRAL_INACTIVE": 409,
    "ERR_NEUTRAL_CREDENTIAL_MISMATCH": 409,
    "ERR_MISSING_TRANSFER_DOCUMENTATION": 409,
    "ERR_BUILDER_DEFAULTED": 409,
    # business safety
    "ERR_STRUCTURAL_ASSESSMENT_REQUIRED": 409,
    "ERR_MEDIATION_NOT_EXHAUSTED": 409,
    "ERR_RISK_CLASS_INELIGIBLE": 409,
    # temporal
    "ERR_SESSION_WINDOW_NOT_STARTED": 409,
    "ERR_COVERAGE_TERM_ELAPSED": 422,
    "ERR_NO_COVERAGE_IN_FORCE": 422,
    "ERR_ESCALATION_WINDOW_ELAPSED": 422,
    "ERR_NEUTRAL_WINDOW_CONFLICT": 409,
    "ERR_COVERAGE_TERM_OVERLAP": 409,
    # referential
    "ERR_TRANSFEREE_IS_CURRENT_OWNER": 422,
    "ERR_PRIOR_CASE_CLAIM_MISMATCH": 422,
    "ERR_OPEN_DISPUTE_BLOCKS_TRANSFER": 409,
    "ERR_ENTRY_NOT_REVERSIBLE": 422,
    # fiscal
    "ERR_BUILDER_POSTURE_FROZEN": 409,
    "ERR_POSTURE_OVERRIDE_REQUIRED": 409,
    "ERR_PAYMENT_EXCEEDS_RESERVE": 422,
    "ERR_COVERAGE_LIMIT_EXCEEDED": 422,
    "ERR_INITIAL_RESERVE_ALREADY_SET": 422,
    "ERR_AUTHORIZATION_BELOW_DISBURSED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 422)
        self.message = message or error_id


def err(error_id, message=None):
    """Build an ApiError whose status comes from the catalogue."""
    return ApiError(error_id, message)


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)

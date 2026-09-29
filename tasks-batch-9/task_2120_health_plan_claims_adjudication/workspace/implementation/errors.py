"""Error catalogue (PRD section 5) and the ApiError exception."""


ERROR_HTTP_STATUS = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_PROVIDER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_COVERAGE_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_CLAIM_LINE_NOT_FOUND": 404,
    "ERR_ACCUMULATOR_NOT_FOUND": 404,
    # --- state ---
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_CLAIM_NOT_PENDED": 409,
    "ERR_CLAIM_NOT_FINALIZED": 409,
    "ERR_CONTRACT_NOT_DRAFT": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_COVERAGE_ALREADY_TERMINATED": 409,
    "ERR_AUTHORIZATION_NOT_REVOCABLE": 409,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_ACCUMULATOR_VERSION": 412,
    # --- business ---
    "ERR_MEMBER_NO_COVERAGE": 422,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_CONTRACT_WINDOW_CONFLICT": 409,
    "ERR_TIMELY_FILING_EXCEEDED": 422,
    "ERR_OTHER_PAYER_EXCEEDS_BILLED": 422,
    "ERR_ACCUMULATOR_NEGATIVE": 422,
    "ERR_CLAIM_NO_LINES": 422,
    "ERR_DUPLICATE_MEMBER_NUMBER": 409,
    "ERR_DUPLICATE_CLAIM_NUMBER": 409,
    "ERR_DUPLICATE_FEE_RATE": 409,
    # --- request shape ---
    "ERR_MISSING_REQUIRED_FIELD": 400,
    "ERR_INVALID_FIELD_VALUE": 400,
    "ERR_INVALID_PAGINATION": 400,
}


class ApiError(Exception):
    """A rejection carrying the PRD error id, its HTTP status and a message."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the seven declared roles.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_PROVIDER_SCOPE_VIOLATION": "A ProviderRep may only act on claims whose provider_id equals its X-User-ID.",
    "ERR_SEGREGATION_OF_DUTIES": "The overriding MedicalDirector must differ from the principal whose adjudication pass produced the pend.",
    "ERR_PLAN_NOT_FOUND": "No benefit plan with that id.",
    "ERR_MEMBER_NOT_FOUND": "No member with that id.",
    "ERR_COVERAGE_NOT_FOUND": "No coverage segment with that id.",
    "ERR_PROVIDER_NOT_FOUND": "No provider with that id.",
    "ERR_CONTRACT_NOT_FOUND": "No provider contract with that id.",
    "ERR_AUTHORIZATION_NOT_FOUND": "No authorization with that id.",
    "ERR_CLAIM_NOT_FOUND": "No claim with that id.",
    "ERR_CLAIM_LINE_NOT_FOUND": "No service line with that id.",
    "ERR_ACCUMULATOR_NOT_FOUND": "No benefit accumulator with that id.",
    "ERR_INVALID_CLAIM_STATE": "The claim's status does not permit this operation.",
    "ERR_CLAIM_NOT_PENDED": "The claim is not PENDED.",
    "ERR_CLAIM_NOT_FINALIZED": "The claim is not FINALIZED.",
    "ERR_CONTRACT_NOT_DRAFT": "The contract is not DRAFT.",
    "ERR_CONTRACT_NOT_ACTIVE": "The contract is not ACTIVE.",
    "ERR_COVERAGE_ALREADY_TERMINATED": "The coverage segment is already TERMINATED.",
    "ERR_AUTHORIZATION_NOT_REVOCABLE": "Only ACTIVE or PARTIALLY_CONSUMED authorizations may be revoked.",
    "ERR_STALE_CLAIM_VERSION": "expected_claim_version does not match the claim's current version.",
    "ERR_STALE_ACCUMULATOR_VERSION": "expected_accumulator_version does not match the accumulator's current version.",
    "ERR_MEMBER_NO_COVERAGE": "The member has no coverage segment on file.",
    "ERR_COVERAGE_OVERLAP": "The coverage interval intersects an existing segment of the same member.",
    "ERR_CONTRACT_WINDOW_CONFLICT": "The contract window is not separated from an existing contract by at least one full clear calendar day.",
    "ERR_TIMELY_FILING_EXCEEDED": "The claim was filed outside the plan's timely filing window.",
    "ERR_OTHER_PAYER_EXCEEDS_BILLED": "other_payer_paid_cents exceeds the claim's total_billed_cents.",
    "ERR_ACCUMULATOR_NEGATIVE": "The correction would drive an accumulator balance below zero.",
    "ERR_CLAIM_NO_LINES": "A claim must carry at least one service line.",
    "ERR_DUPLICATE_MEMBER_NUMBER": "member_number is already in use.",
    "ERR_DUPLICATE_CLAIM_NUMBER": "claim_number is already in use.",
    "ERR_DUPLICATE_FEE_RATE": "A fee schedule rate already exists for that plan, procedure code and effective date.",
    "ERR_MISSING_REQUIRED_FIELD": "A required field is missing from the request body.",
    "ERR_INVALID_FIELD_VALUE": "A supplied field value is not well formed.",
    "ERR_INVALID_PAGINATION": "limit must be an integer within 1..100 and offset a non-negative integer.",
}

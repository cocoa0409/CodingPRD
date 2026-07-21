"""Error catalog (PRD 5 / SCAFFOLD errors) and the ApiError exception."""

# error_id -> (http_status, default message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers missing or role unknown."),
    "ERR_FORBIDDEN_ROLE": (403, "Role is not permitted for this operation."),
    "ERR_NOT_FOUND": (404, "A referenced resource does not exist."),
    "ERR_NOT_RESOURCE_OWNER": (403, "Caller does not own the target resource."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "Acting user must differ from the recorded actor."),
    "ERR_INVALID_REQUEST": (422, "Request body is malformed."),
    "ERR_INVALID_STATE": (409, "Resource is not in a state that allows this transition."),
    "ERR_GUARANTEE_NOT_ACTIVE": (409, "Claim filed against a guarantee that is not ACTIVE."),
    "ERR_APPLICANT_NOT_VERIFIED": (409, "Applicant is not VERIFIED."),
    "ERR_AGREEMENT_NOT_ACTIVE": (409, "No ACTIVE agreement exists for this guarantee."),
    "ERR_GUARANTEE_NOT_APPROVED": (409, "Guarantee is not APPROVED."),
    "ERR_COMPLIANCE_HOLD": (409, "An OPEN compliance review blocks this operation."),
    "ERR_CLAIM_WINDOW_CLOSED": (409, "Claim filed after the notice period."),
    "ERR_APPLICANT_COVERAGE_OVERLAP": (409, "Applicant already has an overlapping active guarantee."),
    "ERR_UNIT_COVERAGE_OVERLAP": (409, "Unit already has an ACTIVE agreement within the buffer window."),
    "ERR_RENT_TO_INCOME_EXCEEDED": (409, "Rent-to-income ratio exceeds the allowed maximum."),
    "ERR_EXPOSURE_CAP_EXCEEDED": (409, "Projected risk-weighted exposure would exceed the cap."),
    "ERR_FEE_NOT_PAID": (409, "The current fee has not been paid."),
    "ERR_COVERAGE_EXHAUSTED": (409, "Guarantee has no remaining coverage."),
    "ERR_STALE_GUARANTEE_VERSION": (412, "expected_guarantee_version does not match the guarantee."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        http, default_msg = ERRORS[error_id]
        self.error_id = error_id
        self.http_status = http
        self.message = message or default_msg
        super().__init__(self.message)

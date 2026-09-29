"""Error catalogue (PRD Section 5) and the ApiError exception."""

ERROR_STATUS = {
    # auth
    "ERR_ROLE_HEADER_MISSING": 400,
    "ERR_UNAUTHORIZED": 403,
    "ERR_IDENTITY_NOT_FOUND": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_EDITOR_LEVEL_MISMATCH": 403,
    # existence
    "ERR_JOURNAL_NOT_FOUND": 404,
    "ERR_EDITOR_NOT_FOUND": 404,
    "ERR_AUTHOR_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_MANUSCRIPT_NOT_FOUND": 404,
    "ERR_EDITOR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_REVIEW_INVITATION_NOT_FOUND": 404,
    "ERR_DECISION_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_ETHICS_CASE_NOT_FOUND": 404,
    "ERR_PRODUCTION_JOB_NOT_FOUND": 404,
    "ERR_APC_INVOICE_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_INTERVAL": 400,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_PARENT_MISMATCH": 409,
    "ERR_CLOCK_REWIND": 409,
    # concurrency
    "ERR_STALE_MANUSCRIPT_VERSION": 412,
    "ERR_STALE_PRODUCTION_JOB_VERSION": 412,
    # state
    "ERR_INVALID_MANUSCRIPT_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_INVALID_INVITATION_STATE": 409,
    "ERR_INVALID_APPEAL_STATE": 409,
    "ERR_INVALID_ETHICS_CASE_STATE": 409,
    "ERR_INVALID_PRODUCTION_STAGE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_TERMINAL_STATE_LOCKED": 409,
    # intake / screening / scope
    "ERR_SUBJECT_AREA_OUT_OF_SCOPE": 409,
    "ERR_INTEGRITY_BLOCK": 409,
    "ERR_FORMATTING_NON_COMPLIANT": 409,
    "ERR_ETHICS_HOLD": 409,
    # assignment
    "ERR_EDITOR_CONFLICT_DECLARED": 409,
    "ERR_EDITOR_WORKLOAD_EXCEEDED": 409,
    "ERR_NO_ELIGIBLE_EDITOR": 409,
    "ERR_ASSIGNMENT_NOT_ACTIVE": 409,
    # reviewing
    "ERR_REVIEWER_CONFLICT": 409,
    "ERR_REVIEWER_WINDOW_CAPACITY": 409,
    "ERR_NO_ELIGIBLE_REVIEWER": 409,
    "ERR_INVITATION_EXPIRED": 409,
    "ERR_INVITATION_NOT_ACCEPTED": 409,
    "ERR_INSUFFICIENT_REVIEWS": 409,
    # decisions / appeals
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_DATA_AVAILABILITY_REQUIRED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    # ethics / licensing / production
    "ERR_RETRACTION_NOT_SUPPORTED": 409,
    "ERR_EMBARGO_NOT_APPLICABLE": 409,
    "ERR_LICENSE_LOCKED": 409,
    "ERR_SLOT_NOT_BOOKED": 409,
    "ERR_TYPESET_SLOT_CONFLICT": 409,
    "ERR_PROOF_ROUND_LIMIT_REACHED": 409,
    "ERR_DEPOSIT_NOT_READY": 409,
    "ERR_PRODUCTION_STAGE_NOT_READY": 409,
    # fees
    "ERR_UNPAID_APC_INVOICE": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 409,
    "ERR_WAIVER_NOT_ALLOWED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_ROLE_HEADER_MISSING": "X-User-Role header is absent or not one of the six declared roles.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_IDENTITY_NOT_FOUND": "X-User-ID is absent or resolves to no persisted identity row.",
    "ERR_NOT_RESOURCE_OWNER": "The acting identity does not own the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of editorial duties forbids this action.",
    "ERR_EDITOR_LEVEL_MISMATCH": "The acting editor's role_level or journal does not match this request.",
    "ERR_INVALID_REQUEST": "The request body is malformed or violates a field constraint.",
    "ERR_INVALID_INTERVAL": "An interval ends before it starts.",
    "ERR_DUPLICATE_KEY": "A declared unique key already exists.",
    "ERR_PARENT_MISMATCH": "The addressed child does not belong to the parent named in the path.",
    "ERR_CLOCK_REWIND": "The logical clock may only move forward.",
    "ERR_TERMINAL_STATE_LOCKED": "The subject is in a terminal state and accepts no further transitions.",
}


class ApiError(Exception):
    """A single business rejection carrying its catalogue id and HTTP status."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)

"""Error catalogue (§5) and the exception type carrying it."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # auth / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_APPEAL_REVIEWER_MISMATCH": 403,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_DEPENDENT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_RECOVERY_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # state
    "ERR_PROGRAM_PHASE_INVALID": 409,
    "ERR_CASE_STATE_INVALID": 409,
    "ERR_DEPENDENT_STATE_INVALID": 409,
    "ERR_SUBMISSION_STATE_INVALID": 409,
    "ERR_APPEAL_STATE_INVALID": 409,
    "ERR_NOTICE_STATE_INVALID": 409,
    "ERR_RECOVERY_STATE_INVALID": 409,
    # optimistic concurrency
    "ERR_STALE_PROGRAM_VERSION": 412,
    "ERR_STALE_DEPENDENT_VERSION": 412,
    # privacy
    "ERR_PRIVACY_REDACTION_REQUIRED": 422,
    "ERR_PRIVACY_HOLD": 422,
    # temporal windows
    "ERR_AMNESTY_WINDOW_CLOSED": 409,
    "ERR_RESPONSE_WINDOW_CLOSED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_CONTINUATION_ELECTION_WINDOW_CLOSED": 409,
    "ERR_REMINDER_CADENCE_VIOLATION": 409,
    # business constraints
    "ERR_REMINDER_LIMIT_REACHED": 409,
    "ERR_CASE_WINDOW_OVERLAP": 409,
    "ERR_APPEAL_ROUNDS_EXHAUSTED": 409,
    "ERR_AMNESTY_ALREADY_RECORDED": 409,
    "ERR_DOCUMENTATION_RULE_CONFLICT": 409,
    "ERR_POE_PROGRAM_AMBIGUOUS": 409,
    "ERR_DUPLICATE_PROGRAM": 409,
    "ERR_OPEN_APPEALS_REMAIN": 409,
    "ERR_OPEN_RECOVERIES_REMAIN": 409,
    # referential / documentation
    "ERR_PROOF_TYPE_NOT_ACCEPTED": 422,
    "ERR_PROOF_STALE_DOCUMENT": 422,
    "ERR_APPEAL_GROUNDS_UNSUPPORTED": 422,
    "ERR_DOCUMENTATION_RULE_MISSING": 422,
    "ERR_SCOPE_PARAMETERS_INVALID": 422,
    "ERR_SCOPE_EMPTY": 422,
    # fiscal
    "ERR_WAIVER_EXCEEDS_SUBTOTAL": 422,
    "ERR_RECOVERY_BELOW_DE_MINIMIS": 422,
    "ERR_PAYMENT_EXCEEDS_DEMAND": 422,
    # transport-level fallbacks
    "ERR_NOT_FOUND": 404,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "An Employee caller may only address their own resources.",
    "ERR_SEGREGATION_OF_DUTIES": "A user who reviewed a proof submission of this dependent may not take the appeal.",
    "ERR_APPEAL_REVIEWER_MISMATCH": "Only the assigned appeal reviewer may decide this appeal.",
    "ERR_PROGRAM_NOT_FOUND": "The audit program does not exist.",
    "ERR_EMPLOYEE_NOT_FOUND": "The employee does not exist.",
    "ERR_DEPENDENT_NOT_FOUND": "The dependent does not exist.",
    "ERR_CASE_NOT_FOUND": "The audit case does not exist.",
    "ERR_SUBMISSION_NOT_FOUND": "The proof submission does not exist.",
    "ERR_APPEAL_NOT_FOUND": "The appeal does not exist.",
    "ERR_NOTICE_NOT_FOUND": "The termination notice does not exist.",
    "ERR_RECOVERY_NOT_FOUND": "The claim recovery does not exist.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_PROGRAM_PHASE_INVALID": "The audit program phase does not permit this operation.",
    "ERR_CASE_STATE_INVALID": "The audit case status does not permit this operation.",
    "ERR_DEPENDENT_STATE_INVALID": "The dependent coverage status does not permit this operation.",
    "ERR_SUBMISSION_STATE_INVALID": "The proof submission status does not permit this operation.",
    "ERR_APPEAL_STATE_INVALID": "The appeal status does not permit this operation.",
    "ERR_NOTICE_STATE_INVALID": "The termination notice status does not permit this operation.",
    "ERR_RECOVERY_STATE_INVALID": "The claim recovery status does not permit this operation.",
    "ERR_STALE_PROGRAM_VERSION": "expected_program_version does not match the program's current version.",
    "ERR_STALE_DEPENDENT_VERSION": "expected_dependent_version does not match the dependent's current version.",
    "ERR_PRIVACY_REDACTION_REQUIRED": "A sensitive proof type must be submitted with redaction_applied true.",
    "ERR_PRIVACY_HOLD": "The submission carries an outstanding privacy obligation and cannot be accepted.",
    "ERR_AMNESTY_WINDOW_CLOSED": "The amnesty window has closed.",
    "ERR_RESPONSE_WINDOW_CLOSED": "The response window has closed.",
    "ERR_APPEAL_WINDOW_CLOSED": "The appeal window has closed.",
    "ERR_CONTINUATION_ELECTION_WINDOW_CLOSED": "The continuation election window has closed.",
    "ERR_REMINDER_CADENCE_VIOLATION": "The reminder cadence gap has not elapsed.",
    "ERR_REMINDER_LIMIT_REACHED": "The case has already received its full reminder allowance.",
    "ERR_CASE_WINDOW_OVERLAP": "An employee would be placed under two intersecting audit response windows.",
    "ERR_APPEAL_ROUNDS_EXHAUSTED": "The appeal round cap has been reached.",
    "ERR_AMNESTY_ALREADY_RECORDED": "An amnesty removal already exists for this dependent.",
    "ERR_DOCUMENTATION_RULE_CONFLICT": "The documentation rule triple is not unique or its grace field is phase-inappropriate.",
    "ERR_POE_PROGRAM_AMBIGUOUS": "Point-of-enrollment program selection could not be reduced to a single program.",
    "ERR_DUPLICATE_PROGRAM": "An audit program with this plan_year and program_name already exists.",
    "ERR_OPEN_APPEALS_REMAIN": "An appeal is still open.",
    "ERR_OPEN_RECOVERIES_REMAIN": "A claim recovery is still outstanding.",
    "ERR_PROOF_TYPE_NOT_ACCEPTED": "The offered proof type is not acceptable for this relationship class.",
    "ERR_PROOF_STALE_DOCUMENT": "The recency-scoped proof document is too old.",
    "ERR_APPEAL_GROUNDS_UNSUPPORTED": "The asserted appeal grounds are unsupported.",
    "ERR_DOCUMENTATION_RULE_MISSING": "No documentation rule exists for a relationship class this operation needs.",
    "ERR_SCOPE_PARAMETERS_INVALID": "The scope parameters do not match the requested scope class.",
    "ERR_SCOPE_EMPTY": "Scope candidate selection produced no employee.",
    "ERR_WAIVER_EXCEEDS_SUBTOTAL": "waiver_credit_cents exceeds recoverable_subtotal_cents.",
    "ERR_RECOVERY_BELOW_DE_MINIMIS": "recoverable_subtotal_cents is below the de minimis floor.",
    "ERR_PAYMENT_EXCEEDS_DEMAND": "The payment would exceed the outstanding demand.",
    "ERR_NOT_FOUND": "The requested resource does not exist.",
}

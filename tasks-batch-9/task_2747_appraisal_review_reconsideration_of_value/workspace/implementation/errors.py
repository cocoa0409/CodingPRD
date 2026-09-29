"""Error catalog for the appraisal desk API.

Every error id / http status pair is taken verbatim from the PRD error
catalog (section 5) and SCAFFOLD.yaml `errors`.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> (http_status, default message)
CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or the role is unrecognized."),
    "ERR_FORBIDDEN_ROLE": (403, "The authenticated role may not perform this operation."),
    "ERR_NOT_RESOURCE_OWNER": (403, "The caller does not own the targeted resource."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The submitter of a desk review may not decide it."),
    "ERR_LOAN_FILE_NOT_FOUND": (404, "Loan file not found."),
    "ERR_APPRAISER_NOT_FOUND": (404, "Appraiser not found."),
    "ERR_AMC_NOT_FOUND": (404, "Appraisal management company not found."),
    "ERR_PANEL_MEMBERSHIP_NOT_FOUND": (404, "Panel membership not found."),
    "ERR_APPRAISAL_NOT_FOUND": (404, "Appraisal not found."),
    "ERR_BIAS_FLAG_NOT_FOUND": (404, "Bias indicator flag not found."),
    "ERR_DESK_REVIEW_NOT_FOUND": (404, "Desk review not found."),
    "ERR_ESCALATION_ORDER_NOT_FOUND": (404, "Escalation order not found."),
    "ERR_ROV_REQUEST_NOT_FOUND": (404, "Reconsideration of value request not found."),
    "ERR_DISPUTE_CASE_NOT_FOUND": (404, "Dispute case not found."),
    "ERR_INVALID_REQUEST": (400, "The request body is malformed."),
    "ERR_INVALID_PAGINATION": (400, "Pagination parameters are out of range."),
    "ERR_STALE_VERSION": (412, "The supplied version does not match the stored version."),
    "ERR_INVALID_STATE": (409, "The resource is not in a state that allows this transition."),
    "ERR_APPRAISAL_GRID_LOCKED": (409, "The comparable grid is locked."),
    "ERR_RULE_CHECKS_NOT_RUN": (409, "The automated rule checks have not been run."),
    "ERR_DESK_REVIEW_NOT_SUBMITTED": (409, "The desk review is not in SUBMITTED."),
    "ERR_ESCALATION_NOT_PENDING": (409, "The escalation order is not awaiting assignment."),
    "ERR_ROV_NOT_AWAITING_RESPONSE": (409, "The reconsideration request is not awaiting an appraiser response."),
    "ERR_DISPUTE_ALREADY_RESOLVED": (409, "The dispute case is already resolved."),
    "ERR_COMMUNICATION_LOCKED": (409, "Communications are locked for this appraisal."),
    "ERR_INSPECTION_WINDOW_CONFLICT": (409, "The inspection window conflicts with an existing assignment."),
    "ERR_DISPUTE_SLOT_CAPACITY_EXCEEDED": (409, "The review slot exceeds the company's concurrent dispute capacity."),
    "ERR_BIAS_SCREEN_REQUIRED": (422, "The bias screen has not been run for this appraisal."),
    "ERR_ESCALATION_REQUIRED": (422, "The decision does not match the required escalation."),
    "ERR_BIAS_QUARANTINE_ACTIVE": (422, "A substantiated bias quarantine is active."),
    "ERR_INDEPENDENCE_VIOLATION": (422, "The communication violates appraiser independence."),
    "ERR_AMC_NOT_ELIGIBLE": (422, "The appraisal management company is suspended."),
    "ERR_APPRAISER_NOT_ON_PANEL": (422, "The appraiser holds no active membership on that panel."),
    "ERR_APPRAISER_INELIGIBLE": (422, "The appraiser is not eligible for this assignment."),
    "ERR_LOAN_NOT_ROV_ELIGIBLE": (422, "The loan file is not eligible for a reconsideration of value."),
    "ERR_DISPUTE_PARTY_MISMATCH": (422, "The dispute parties do not match the appraisal."),
    "ERR_COMP_DATE_AFTER_EFFECTIVE": (422, "The comparable sale date is after the appraisal effective date."),
    "ERR_INVALID_WINDOW": (422, "The supplied interval is not well formed."),
    "ERR_DISPUTE_DEADLINE_NOT_REACHED": (422, "The response deadline has not been reached."),
    "ERR_DUPLICATE_COMPARABLE": (422, "A comparable with that street address already exists on this appraisal."),
    "ERR_COMP_LIMIT_EXCEEDED": (422, "The comparable grid already holds the maximum number of comparables."),
    "ERR_DUPLICATE_PANEL_MEMBERSHIP": (422, "An active membership already exists for that appraiser and company."),
    "ERR_INSUFFICIENT_ADMISSIBLE_EVIDENCE": (422, "The reconsideration request lacks enough admissible evidence."),
    "ERR_ROV_ROUND_LIMIT": (422, "The reconsideration round limit has been reached."),
    "ERR_PANEL_ACTION_NOT_PERMITTED": (422, "The panel action is not permitted from the current standing."),
    "ERR_REVISION_EXCEEDS_CAP": (422, "The proposed value revision exceeds the allowed cap."),
    "ERR_DUPLICATE_DISPUTE_BASIS": (422, "An unresolved dispute already exists for that basis."),
    "ERR_ESCALATION_BUDGET_EXCEEDED": (402, "The escalation would exceed the company's budget."),
}

_DEFAULT_MESSAGES = {k: v[1] for k, v in CATALOG.items()}


def fail(error_id, message=None):
    status = CATALOG[error_id][0]
    raise ApiError(error_id, status, message)

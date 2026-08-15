"""Error type carrying the scaffold-declared error_id / http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# Convenience constructors — ids and statuses from the scaffold error catalog.
def missing_user_context(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def forbidden_role(msg="Role is not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def wrong_subcontractor(msg="X-User-ID does not match the responsible/addressed subcontractor"):
    return ApiError("ERR_WRONG_SUBCONTRACTOR", 403, msg)


def reviewer_not_assigned(msg="X-User-ID is not the assigned reviewer for this resource"):
    return ApiError("ERR_REVIEWER_NOT_ASSIGNED", 403, msg)


def project_not_found(msg="Project not found"):
    return ApiError("ERR_PROJECT_NOT_FOUND", 404, msg)


def spec_section_not_found(msg="Spec section not found"):
    return ApiError("ERR_SPEC_SECTION_NOT_FOUND", 404, msg)


def subcontractor_not_found(msg="Subcontractor not found"):
    return ApiError("ERR_SUBCONTRACTOR_NOT_FOUND", 404, msg)


def reviewer_not_found(msg="Reviewer not found"):
    return ApiError("ERR_REVIEWER_NOT_FOUND", 404, msg)


def submittal_not_found(msg="Submittal not found"):
    return ApiError("ERR_SUBMITTAL_NOT_FOUND", 404, msg)


def revision_not_found(msg="Revision not found"):
    return ApiError("ERR_REVISION_NOT_FOUND", 404, msg)


def rfi_not_found(msg="RFI not found"):
    return ApiError("ERR_RFI_NOT_FOUND", 404, msg)


def assessment_not_found(msg="Impact assessment not found"):
    return ApiError("ERR_ASSESSMENT_NOT_FOUND", 404, msg)


def activity_not_found(msg="Installation activity not found"):
    return ApiError("ERR_ACTIVITY_NOT_FOUND", 404, msg)


def report_not_found(msg="Owner report not found"):
    return ApiError("ERR_REPORT_NOT_FOUND", 404, msg)


def lli_not_found(msg="Long-lead item not found"):
    return ApiError("ERR_LONG_LEAD_ITEM_NOT_FOUND", 404, msg)


def distribution_not_found(msg="Distribution record not found"):
    return ApiError("ERR_DISTRIBUTION_NOT_FOUND", 404, msg)


def invalid_request(msg="Request body is missing a required field or is malformed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_date_range(msg="Date range is invalid"):
    return ApiError("ERR_INVALID_DATE_RANGE", 400, msg)


def stale_project_version(msg="expected_project_version is stale"):
    return ApiError("ERR_STALE_PROJECT_VERSION", 412, msg)


def stale_submittal_version(msg="expected_submittal_version is stale"):
    return ApiError("ERR_STALE_SUBMITTAL_VERSION", 412, msg)


def project_not_active(msg="Project posture does not permit this mutation"):
    return ApiError("ERR_PROJECT_NOT_ACTIVE", 409, msg)


def invalid_project_state(msg="Project posture does not permit this transition"):
    return ApiError("ERR_INVALID_PROJECT_STATE", 409, msg)


def spec_section_not_draft(msg="Spec section is not in DRAFT"):
    return ApiError("ERR_SPEC_SECTION_NOT_DRAFT", 409, msg)


def spec_section_not_active(msg="Spec section is not in ACTIVE"):
    return ApiError("ERR_SPEC_SECTION_NOT_ACTIVE", 409, msg)


def submittal_not_accepting_revisions(msg="Submittal does not accept revisions in its current state"):
    return ApiError("ERR_SUBMITTAL_NOT_ACCEPTING_REVISIONS", 409, msg)


def submittal_not_approved(msg="Submittal is not APPROVED"):
    return ApiError("ERR_SUBMITTAL_NOT_APPROVED", 409, msg)


def submittal_not_distributed(msg="Submittal is not DISTRIBUTED"):
    return ApiError("ERR_SUBMITTAL_NOT_DISTRIBUTED", 409, msg)


def submittal_terminal(msg="Submittal is in a terminal state"):
    return ApiError("ERR_SUBMITTAL_TERMINAL", 409, msg)


def revision_not_submitted(msg="Revision is not SUBMITTED"):
    return ApiError("ERR_REVISION_NOT_SUBMITTED", 409, msg)


def revision_not_under_review(msg="Revision is not UNDER_REVIEW"):
    return ApiError("ERR_REVISION_NOT_UNDER_REVIEW", 409, msg)


def rfi_invalid_state(msg="RFI status does not permit this transition"):
    return ApiError("ERR_RFI_INVALID_STATE", 409, msg)


def assessment_not_estimated(msg="Impact assessment is not ESTIMATED"):
    return ApiError("ERR_ASSESSMENT_NOT_ESTIMATED", 409, msg)


def assessment_not_priced(msg="Impact assessment is not in the required state"):
    return ApiError("ERR_ASSESSMENT_NOT_PRICED", 409, msg)


def distribution_not_queued(msg="Distribution record is not QUEUED"):
    return ApiError("ERR_DISTRIBUTION_NOT_QUEUED", 409, msg)


def distribution_not_sent(msg="Distribution record is not SENT"):
    return ApiError("ERR_DISTRIBUTION_NOT_SENT", 409, msg)


def activity_not_planned(msg="Installation activity is not PLANNED"):
    return ApiError("ERR_ACTIVITY_NOT_PLANNED", 409, msg)


def activity_not_released(msg="Installation activity is not RELEASED"):
    return ApiError("ERR_ACTIVITY_NOT_RELEASED", 409, msg)


def report_not_draft(msg="Owner report is not DRAFT"):
    return ApiError("ERR_REPORT_NOT_DRAFT", 409, msg)


def deferral_not_pending(msg="Deferral is not in the required pending state"):
    return ApiError("ERR_DEFERRAL_NOT_PENDING", 409, msg)


def lli_invalid_advance(msg="Long-lead item advance target is not the next procurement step"):
    return ApiError("ERR_LLI_INVALID_ADVANCE", 409, msg)


def segregation_of_duties(msg="Accept must be performed by a different user than priced"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION", 403, msg)


def subcontractor_suspended(msg="Subcontractor standing is SUSPENDED"):
    return ApiError("ERR_SUBCONTRACTOR_SUSPENDED", 409, msg)


def discipline_mismatch(msg="Reviewer discipline does not match the required discipline"):
    return ApiError("ERR_DISCIPLINE_MISMATCH", 409, msg)


def reviewer_at_capacity(msg="Reviewer is at capacity"):
    return ApiError("ERR_REVIEWER_AT_CAPACITY", 409, msg)


def no_eligible_reviewer(msg="No eligible reviewer available"):
    return ApiError("ERR_NO_ELIGIBLE_REVIEWER", 409, msg)


def already_distributed(msg="Distribution records already exist"):
    return ApiError("ERR_ALREADY_DISTRIBUTED", 409, msg)


def no_distribution_targets(msg="Affected subcontractor set is empty"):
    return ApiError("ERR_NO_DISTRIBUTION_TARGETS", 409, msg)


def crew_window_conflict(msg="Crew window conflict"):
    return ApiError("ERR_CREW_WINDOW_CONFLICT", 409, msg)


def submittal_not_released(msg="Submittal is not in a released-class state"):
    return ApiError("ERR_SUBMITTAL_NOT_RELEASED", 409, msg)


def open_rfi_blocks_release(msg="Open RFI blocks release"):
    return ApiError("ERR_OPEN_RFI_BLOCKS_RELEASE", 409, msg)


def open_rfi_blocks_close(msg="Open RFI blocks close"):
    return ApiError("ERR_OPEN_RFI_BLOCKS_CLOSE", 409, msg)


def long_lead_not_delivered(msg="Long-lead item is not DELIVERED"):
    return ApiError("ERR_LONG_LEAD_NOT_DELIVERED", 409, msg)


def closeout_blocked(msg="Begin-closeout preconditions not met"):
    return ApiError("ERR_CLOSEOUT_BLOCKED", 409, msg)


def assessment_open_on_close(msg="Non-terminal impact assessment blocks close"):
    return ApiError("ERR_ASSESSMENT_OPEN_ON_CLOSE", 409, msg)


def reopen_blocked_by_priced(msg="A PRICED or DISPUTED impact assessment blocks reopen"):
    return ApiError("ERR_REOPEN_BLOCKED_BY_PRICED_ASSESSMENT", 409, msg)


def contingency_exhausted(msg="Reservation exceeds contingency_available_cents"):
    return ApiError("ERR_CONTINGENCY_EXHAUSTED", 402, msg)

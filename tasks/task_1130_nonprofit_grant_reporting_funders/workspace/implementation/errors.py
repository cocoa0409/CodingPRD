"""Error classes and error ID constants for the Nonprofit Grant Reporting API."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role is not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_validation(msg="Validation error"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Invalid state for this operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_grant_not_active(msg="Grant is not ACTIVE"):
    return ApiError("ERR_GRANT_NOT_ACTIVE", 409, msg)


def err_grant_suspended(msg="Grant is SUSPENDED"):
    return ApiError("ERR_GRANT_SUSPENDED", 409, msg)


def err_report_not_editable(msg="Report is not editable"):
    return ApiError("ERR_REPORT_NOT_EDITABLE", 409, msg)


def err_expense_not_posted(msg="Expense is not POSTED"):
    return ApiError("ERR_EXPENSE_NOT_POSTED", 409, msg)


def err_modification_not_pending(msg="Modification request is not pending"):
    return ApiError("ERR_MODIFICATION_NOT_PENDING", 409, msg)


def err_finding_not_open(msg="Finding is not in the required state"):
    return ApiError("ERR_FINDING_NOT_OPEN", 409, msg)


def err_expense_locked(msg="Expense is locked by a submitted report"):
    return ApiError("ERR_EXPENSE_LOCKED_BY_REPORT", 409, msg)


def err_duplicate_award(msg="award_number already used for this funder"):
    return ApiError("ERR_DUPLICATE_AWARD_NUMBER", 409, msg)


def err_engagement_overlap(msg="Engagement window overlaps another engagement on this grant"):
    return ApiError("ERR_ENGAGEMENT_OVERLAP", 409, msg)


def err_auditor_capacity(msg="Auditor org would exceed maximum concurrent engagements"):
    return ApiError("ERR_AUDITOR_CAPACITY", 409, msg)


def err_stale_version(msg="expected_grant_version does not match grant.version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_not_balanced(msg="BUDGET_REALLOCATION line_deltas do not sum to zero"):
    return ApiError("ERR_REALLOCATION_NOT_BALANCED", 422, msg)


def err_below_expended(msg="Reallocation would push adjusted_cents below expended_cents"):
    return ApiError("ERR_REALLOCATION_BELOW_EXPENDED", 422, msg)


def err_extension_not_forward(msg="requested_end_date is not strictly after current end_date"):
    return ApiError("ERR_EXTENSION_NOT_FORWARD", 422, msg)


def err_restriction(msg="Restricted fund does not allow this budget line category"):
    return ApiError("ERR_RESTRICTION_VIOLATION", 422, msg)


def err_line_exceeded(msg="Allocation would push budget line expended above adjusted_cents"):
    return ApiError("ERR_BUDGET_LINE_EXCEEDED", 422, msg)


def err_fund_exceeded(msg="Allocation would push fund expended above allocated_cents"):
    return ApiError("ERR_FUND_EXCEEDED", 422, msg)


def err_overallocated(msg="Allocation amount exceeds expense.unallocated_cents"):
    return ApiError("ERR_EXPENSE_OVERALLOCATED", 422, msg)


def err_variance_required(msg="A budget line breaching the variance threshold lacks an explanation"):
    return ApiError("ERR_VARIANCE_EXPLANATION_REQUIRED", 422, msg)


def err_outcome_required(msg="narrative_draft must be non-empty and outcome_entries non-empty"):
    return ApiError("ERR_OUTCOME_DATA_REQUIRED", 422, msg)


def err_match_shortfall(msg="Verified match is below required_match_cents"):
    return ApiError("ERR_MATCH_SHORTFALL", 422, msg)


def err_renewal_not_open(msg="Renewal window is not open"):
    return ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN", 409, msg)


def err_renewal_lapsed(msg="Renewal window has lapsed"):
    return ApiError("ERR_RENEWAL_WINDOW_LAPSED", 409, msg)

"""Custom error class carrying error_id, http_status, and message.

Every domain error in the system is raised as an ApiError and translated into
the standard error response envelope by the global Flask error handler.
"""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Pre-defined error definitions keyed by error_id (HTTP status, default message).
ERROR_DEFINITIONS = {
    "ERR_BAD_REQUEST": (400, "Malformed JSON or missing required input field."),
    "ERR_UNAUTHENTICATED": (401, "X-User-Role header missing or unknown."),
    "ERR_FORBIDDEN": (403, "Role not permitted for this endpoint."),
    "ERR_NOT_FOUND": (404, "Resource not found."),
    "ERR_INVALID_STATE": (409, "Resource is not in a state from which the requested transition is defined."),
    "ERR_AUTOMATIC_STAY_VIOLATION": (409, "Collection action rejected: automatic stay is active."),
    "ERR_NOT_CHAPTER_13": (409, "Operation requires chapter_effective=CHAPTER_13."),
    "ERR_MEETING_TOO_EARLY": (422, "Meeting date must be at least 21 days after filing date."),
    "ERR_MEETING_DATE_NOT_REACHED": (409, "Server clock has not reached the scheduled meeting date."),
    "ERR_SCHEDULES_INCOMPLETE": (409, "Case schedule_completeness is non-empty; all 10 schedules must be submitted."),
    "ERR_MEANS_TEST_NOT_RUN": (409, "Case has no MeansTestResult; means test must be run before filing."),
    "ERR_PRESUMPTION_OF_ABUSE": (409, "Chapter 7 filing blocked: presumption_of_abuse is true."),
    "ERR_PLAN_UNDERFUNDED": (422, "Plan planned_total_cents is less than minimum_plan_total_cents."),
    "ERR_PLAN_MONTHS_MISMATCH": (422, "Plan plan_months does not equal required_plan_months from means test."),
    "ERR_PLAN_NOT_COMPLETE": (409, "Plan paid_to_date_cents is less than planned_total_cents."),
    "ERR_PLAN_IN_DEFAULT": (409, "Plan has at least one MISSED payment; cannot discharge."),
    "ERR_DISMISSAL_NOT_WARRANTED": (409, "Dismissal from IN_REPAYMENT requires missed_payment_count >= 3."),
    "ERR_CLAIM_AMOUNT_INVALID": (422, "Claim amount_cents must be strictly greater than zero."),
    "ERR_CLAIM_CLASS_MISMATCH": (422, "Claim claim_class must equal the registered creditor's creditor_type."),
    "ERR_PAYMENT_SEQUENCE_DUPLICATE": (409, "TrusteePayment sequence_number is duplicate or out of range."),
    "ERR_PLAN_ALREADY_EXISTS": (409, "Case already has an active Plan in {PROPOSED, CONFIRMED, IN_REPAYMENT}."),
    "ERR_STALE_DATA": (409, "Optimistic concurrency check failed: stale version."),
}


def make_error(error_id: str, message: str | None = None) -> ApiError:
    """Build an ApiError for one of the cataloged errors."""
    http, default_msg = ERROR_DEFINITIONS.get(error_id, (500, "Internal error"))
    return ApiError(error_id, http, message or default_msg)

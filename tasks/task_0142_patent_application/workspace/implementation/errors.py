"""Custom ApiError class and error catalog (SCAFFOLD §1.6).

Each domain error is raised as an ApiError and translated to the standard
error envelope by the global Flask error handler. The error_id strings and
HTTP status codes here match the SCAFFOLD §1.6 catalog exactly.
"""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Pre-defined error definitions keyed by error_id.
# Source: SCAFFOLD §1.6 + PRD §5.
ERROR_DEFINITIONS = {
    "ERR_BAD_REQUEST": (400, "Malformed request body or invalid input field."),
    "ERR_UNAUTHENTICATED": (401, "X-User-ID or X-User-Role header missing."),
    "ERR_FORBIDDEN": (403, "Role not permitted for the requested operation, or ownership check failed."),
    "ERR_NOT_FOUND": (404, "Resource not found."),
    "ERR_INVALID_STATE": (409, "Resource is not in a state from which the requested transition is permitted."),
    "ERR_VERSION_CONFLICT": (409, "Optimistic concurrency: supplied version does not match current entity version."),
    "ERR_IDEMPOTENCY_CONFLICT": (409, "Idempotency-Key reused with a different request payload within 24h."),
    "ERR_OFFICE_ACTION_DEADLINE_PASSED": (409, "Office Action response filed after extended_deadline_at."),
    "ERR_MAINTENANCE_WINDOW_CLOSED": (409, "Maintenance fee payment outside [window_open_at, grace_period_end_at]."),
    "ERR_PCT_DEADLINE_PASSED": (409, "National phase entry attempted after national_phase_deadline_at."),
    "ERR_PARENT_NOT_PENDING": (
        422,
        "Continuation/CIP filing references a parent that is not pending or is PROVISIONAL.",
    ),
    "ERR_CLAIM_SHAPE_INVALID": (422, "Claim counts violate type-specific constraints."),
    "ERR_MICRO_INELIGIBLE": (422, "Applicant declared MICRO but does not meet income / prior-filings caps."),
    "ERR_MAINTENANCE_NOT_APPLICABLE": (422, "Maintenance fee accessed for a non-UTILITY or non-GRANTED application."),
    "ERR_PCT_INELIGIBLE": (422, "PCT initiation requires UTILITY application in FILED/UNDER_EXAMINATION/OFFICE_ACTION_PENDING."),
    "ERR_FEE_AMOUNT_MISMATCH": (422, "Provided fee amount_cents does not equal the scaffold-computed amount."),
    "ERR_FEE_CATEGORY_INVALID": (422, "Fee category not appropriate for this endpoint or context."),
    "ERR_APPLICANT_SUSPENDED": (403, "Applicant is SUSPENDED and cannot perform write operations."),
    "ERR_VALIDATION": (422, "Generic input validation failure."),
}


def make_error(error_id: str, message: str | None = None) -> ApiError:
    """Build an ApiError for one of the cataloged errors."""
    http, default_msg = ERROR_DEFINITIONS.get(error_id, (500, "Internal error"))
    return ApiError(error_id, http, message or default_msg)

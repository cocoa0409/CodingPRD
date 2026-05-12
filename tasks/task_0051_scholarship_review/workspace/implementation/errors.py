"""Error definitions and exceptions."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status (per §5 of the PRD).
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_WINDOW_NOT_OPEN": 409,
    "ERR_WINDOW_CLOSED": 409,
    "ERR_WINDOW_NOT_CLOSED": 409,
    "ERR_RUBRIC_WEIGHT_INVALID": 422,
    "ERR_QUOTA_MISMATCH": 422,
    "ERR_ELIGIBILITY_FAIL": 422,
    "ERR_MATERIAL_MISSING": 422,
    "ERR_MATERIAL_INCOMPLETE": 422,
    "ERR_ADVISOR_REC_MISSING": 422,
    "ERR_DUPLICATE_APPLICATION_SAME": 409,
    "ERR_DUPLICATE_APPLICATION_CROSS": 409,
    "ERR_COMMENT_REQUIRED": 422,
    "ERR_DEPT_SCOPE_MISMATCH": 403,
    "ERR_COI_VIOLATION": 409,
    "ERR_REVIEWER_COUNT_INVALID": 422,
    "ERR_REVIEWER_DUPLICATE": 422,
    "ERR_REVIEWER_NOT_ACTIVE": 409,
    "ERR_REVIEWERS_ALREADY_ASSIGNED": 409,
    "ERR_SCORE_RUBRIC_MISMATCH": 422,
    "ERR_SCORE_OVER_QUOTA": 409,
    "ERR_REVIEW_NOT_COMPLETE": 409,
    "ERR_OBJECTION_PENDING": 409,
    "ERR_DISBURSEMENT_NOT_EXECUTED": 409,
    "ERR_PLAN_EMPTY": 409,
    "ERR_SOD_VIOLATION": 403,
    "ERR_EXECUTOR_MISMATCH": 403,
    "ERR_BAD_REQUEST": 400,
    "ERR_SCHOLARSHIP_WINDOW_OVERLAP": 409,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    if error_id not in ERROR_CATALOG:
        # Defensive: any unknown id is escalated as 500-ish 422 with the literal id.
        return APIError(error_id, message or error_id, 422)
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

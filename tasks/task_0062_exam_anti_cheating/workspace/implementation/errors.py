"""Error classes and canonical error catalog per PRD §5."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Canonical error catalog: error_id -> http_status
ERROR_CATALOG = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # Existence
    "ERR_EXAM_NOT_FOUND": 404,
    "ERR_QUESTION_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_ATTEMPT_NOT_FOUND": 404,
    "ERR_GRADING_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    # State
    "ERR_INVALID_STATE": 409,
    "ERR_EXAM_NOT_IN_SESSION": 409,
    "ERR_EXAM_NOT_GRADING": 409,
    "ERR_EXAM_NOT_IN_APPEAL_WINDOW": 409,
    "ERR_GRADING_INCOMPLETE": 409,
    "ERR_EXAM_WINDOW_CLOSED": 409,
    "ERR_NO_PENDING_RECHECK": 409,
    # Grading invariants
    "ERR_GRADING_ALREADY_CLAIMED": 409,
    "ERR_DOUBLE_BLIND_VIOLATION": 409,
    "ERR_APPEAL_OFFICER_WAS_MARKER": 409,
    # Identity / safety
    "ERR_IDENTITY_MISMATCH": 422,
    "ERR_EVIDENCE_REQUIRED": 422,
    "ERR_AWARDED_OUT_OF_RANGE": 422,
    "ERR_RUBRIC_SUM_MISMATCH": 422,
    "ERR_RUBRIC_INVALID": 422,
    "ERR_QUESTION_NOT_ON_PAPER": 422,
    "ERR_QUESTION_BANK_EMPTY": 422,
    "ERR_SAMPLING_INFEASIBLE": 422,
    # Pagination
    "ERR_INVALID_PAGINATION_PARAMETERS": 400,
}


def err(error_id: str, message: str = "") -> APIError:
    if error_id not in ERROR_CATALOG:
        # Defensive — should never happen.
        return APIError(error_id, message or error_id, 400)
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])

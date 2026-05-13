"""Error catalog for the Crowdsource Design API."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Catalog: error_id -> default HTTP status (per PRD §5).
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_ORIGINAL_DECLARATION_REQUIRED": 422,
    "ERR_REVIEWER_CONFLICT_OF_INTEREST": 422,
    "ERR_REVIEWER_NOT_QUALIFIED": 422,
    "ERR_REVIEWER_CAPACITY_EXCEEDED": 422,
    "ERR_MODIFY_WINDOW_CLOSED": 422,
    "ERR_REVIEW_WINDOW_CLOSED": 422,
    "ERR_TIMELINE_TOO_TIGHT": 422,
    "ERR_STAGE_OVERLAP": 422,
    "ERR_SUBMISSION_LIMIT_REACHED": 422,
    "ERR_RUBRIC_WEIGHTS_INVALID": 422,
    "ERR_CRITERION_SCORES_INVALID": 422,
    "ERR_TRANSFER_SCOPE_INVALID": 422,
    "ERR_SIGNATURE_OUT_OF_ORDER": 409,
    "ERR_COPYRIGHT_NOT_REGISTERED": 422,
    "ERR_PRIZE_POOL_MISMATCH": 422,
    "ERR_PRIZE_AMOUNT_INVALID": 422,
    "ERR_QUORUM_NOT_MET": 422,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_DISPUTE_PENDING": 409,
    "ERR_REVIEWER_ALREADY_ASSIGNED": 409,
    "ERR_STAGE_ALREADY_PUBLISHED": 409,
    "ERR_DUPLICATE_IDEMPOTENCY_KEY": 409,
    "ERR_VALIDATION": 422,
}


def api_error(error_id: str, message: str = ""):
    http = ERRORS.get(error_id, 400)
    return APIError(error_id, http, message or error_id)

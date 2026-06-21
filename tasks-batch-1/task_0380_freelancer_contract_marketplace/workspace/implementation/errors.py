"""Error classes and the complete error catalogue (PRD section 5)."""


class ApiError(Exception):
    """Carries an error_id, http status and human-readable message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error_id (PRD section 5 — Error Code Catalogue).
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_FREELANCER_NOT_FOUND": 404,
    "ERR_JOB_POSTING_NOT_FOUND": 404,
    "ERR_PROPOSAL_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_TIMELOG_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_TAX_RECORD_NOT_FOUND": 404,
    "ERR_SKILLS_NOT_COVERED": 422,
    "ERR_INVALID_PROPOSAL_STATE": 409,
    "ERR_NOT_YOUR_TURN": 409,
    "ERR_INVALID_CONTRACT_STATE": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_INVALID_MILESTONE_STATE": 409,
    "ERR_NO_VERIFIED_TIMELOGS": 409,
    "ERR_INVALID_TIMELOG_STATE": 409,
    "ERR_TIMELOG_OVERLAP": 409,
    "ERR_DAILY_HOURS_CAP_EXCEEDED": 409,
    "ERR_INVALID_DISPUTE_STATE": 409,
    "ERR_AWARD_OUT_OF_RANGE": 422,
    "ERR_CONTRACT_HAS_OPEN_ITEMS": 409,
    "ERR_INVALID_PAYOUT_STATE": 409,
    "ERR_REVIEW_CONTRACT_NOT_COMPLETED": 409,
    "ERR_INSUFFICIENT_WALLET": 402,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_DUPLICATE_MILESTONE_ORDINAL": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalogue's HTTP status for error_id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)

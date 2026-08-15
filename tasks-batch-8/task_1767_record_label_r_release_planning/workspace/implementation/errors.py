"""Error types and error-id constants for the Record Label API."""


class ApiError(Exception):
    """Exception carrying the scaffold-defined error surface."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalog (id -> http status)
ERRORS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_ARTIST_OWNERSHIP_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_GUARDIAN_CONSENT_REQUIRED": 422,
    "ERR_SAMPLE_CLEARANCE_MISSING": 422,
    "ERR_DEAL_MEMO_ALREADY_OPEN": 409,
    "ERR_SCOUTING_SCORE_TOO_LOW": 422,
    "ERR_DEAL_MEMO_EXPIRED": 422,
    "ERR_ADVANCE_CAP_EXCEEDED": 422,
    "ERR_RENEGOTIATION_IN_PROGRESS": 409,
    "ERR_OPTION_WINDOW_CLOSED": 422,
    "ERR_UNRECOUPED_BALANCE": 422,
    "ERR_CONTRACT_NOT_FUNDED": 409,
    "ERR_ARTIST_NOT_SIGNABLE": 409,
    "ERR_PROJECT_BUDGET_EXCEEDED": 422,
    "ERR_BUDGET_BELOW_SPEND": 422,
    "ERR_MILESTONE_SEQUENCE_CONFLICT": 409,
    "ERR_ISRC_CONFLICT": 409,
    "ERR_SINGLE_TRACK_COUNT": 422,
    "ERR_TRACKS_NOT_CLEARED": 422,
    "ERR_COVER_ART_MISSING": 422,
    "ERR_ASSETS_NOT_LOCKED": 409,
    "ERR_RELEASE_LEAD_TIME": 422,
    "ERR_DISTRIBUTOR_INACTIVE": 422,
    "ERR_DUPLICATE_DELIVERY": 409,
    "ERR_RELEASE_DATE_NOT_REACHED": 422,
    "ERR_BEAT_OUTSIDE_WINDOW": 422,
    "ERR_BEAT_WINDOW_OVERLAP": 409,
    "ERR_CAMPAIGN_WINDOW_CONFLICT": 409,
    "ERR_CAMPAIGN_CAP_EXCEEDED": 422,
    "ERR_APPROVED_EXCEEDS_REQUESTED": 422,
    "ERR_CATEGORY_CAP_EXCEEDED": 422,
    "ERR_TOUR_BUDGET_EXCEEDED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_DUPLICATE_REVENUE_REPORT": 409,
    "ERR_RELEASE_NOT_LIVE": 422,
    "ERR_RUN_PERIOD_CONFLICT": 409,
    "ERR_RUN_HAS_UNPAID_STATEMENTS": 409,
    "ERR_NEGATIVE_PAYABLE": 422,
}


def raise_err(error_id, message=None):
    status = ERRORS[error_id]
    raise ApiError(error_id, status, message or error_id)

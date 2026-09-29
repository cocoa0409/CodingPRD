"""Error catalogue — PRD section 5 / SCAFFOLD 1.6.

Every error_id maps to exactly the HTTP status the PRD catalogue declares.
"""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_RESTRUCTURING_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_LETTER_OF_INTENT_NOT_FOUND": 404,
    "ERR_DILIGENCE_REQUEST_NOT_FOUND": 404,
    "ERR_RESTRICTED_FUND_NOT_FOUND": 404,
    "ERR_BOARD_APPROVAL_NOT_FOUND": 404,
    "ERR_AG_FILING_NOT_FOUND": 404,
    "ERR_INTEGRATION_TASK_NOT_FOUND": 404,
    "ERR_NOT_DEAL_PARTY": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_STALE_RESTRUCTURING_VERSION": 412,
    "ERR_INVALID_DEAL_STATE": 409,
    "ERR_INVALID_LETTER_STATE": 409,
    "ERR_INVALID_FUND_STATE": 409,
    "ERR_INVALID_APPROVAL_STATE": 409,
    "ERR_INVALID_FILING_STATE": 409,
    "ERR_INVALID_TASK_STATE": 409,
    "ERR_INVALID_DILIGENCE_STATE": 409,
    "ERR_SELF_RESTRUCTURING": 422,
    "ERR_ORGANIZATION_NOT_ELIGIBLE": 422,
    "ERR_EIN_ALREADY_REGISTERED": 422,
    "ERR_FUND_NOT_DEAL_PARTY_ASSET": 422,
    "ERR_PROGRAM_NOT_DEAL_PARTY_ASSET": 422,
    "ERR_DEPENDENCY_NOT_IN_SAME_DEAL": 422,
    "ERR_JUDICIAL_ORDER_REQUIRED": 422,
    "ERR_DONOR_CONSENT_REQUIRED": 422,
    "ERR_HDV_EXCEEDS_FUND_VALUE": 422,
    "ERR_AG_REVIEW_NOT_REQUIRED": 422,
    "ERR_AG_STATE_NOT_APPLICABLE": 422,
    "ERR_AG_FILING_TYPE_MISMATCH": 422,
    "ERR_AG_APPROVAL_MISSING": 422,
    "ERR_CONFLICT_DISCLOSURE_MISSING": 422,
    "ERR_VOTE_TALLY_EXCEEDS_SEATS": 422,
    "ERR_QUORUM_NOT_MET": 422,
    "ERR_NO_ELIGIBLE_VOTES": 422,
    "ERR_EXCLUSIVITY_CONFLICT": 409,
    "ERR_EXCLUSIVITY_COOLING_OFF": 409,
    "ERR_CREW_WINDOW_CONFLICT": 409,
    "ERR_DEPENDENCY_NOT_COMPLETE": 409,
    "ERR_STRUCTURE_TYPE_MISMATCH": 422,
    "ERR_SEAT_SPLIT_OUT_OF_RANGE": 422,
    "ERR_RESTRICTED_ASSETS_UNRESOLVED": 409,
    "ERR_INTEGRATION_INCOMPLETE": 409,
    "ERR_ALIGNMENT_RATING_INSUFFICIENT": 422,
    "ERR_RESERVE_BELOW_FLOOR": 422,
    "ERR_NO_CHARITABLE_ASSETS_TRANSFERRED": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_ROLE_NOT_PERMITTED": "The supplied role is not authorized for this endpoint.",
    "ERR_INVALID_REQUEST": "The request could not be validated.",
}


class ApiError(Exception):
    """Carries an error_id, a human readable message and the HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)

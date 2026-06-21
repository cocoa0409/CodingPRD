"""Error classes and the canonical error catalogue (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical HTTP status for every error id (PRD §5 Error Code Catalogue).
ERROR_HTTP = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    # Ownership
    "ERR_NOT_APPLICATION_OWNER": 403,
    "ERR_NOT_SCORE_OWNER": 403,
    "ERR_NOT_ASSIGNMENT_OWNER": 403,
    # Not found
    "ERR_FUND_NOT_FOUND": 404,
    "ERR_CRITERIA_NOT_FOUND": 404,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_COMMITTEE_MEMBER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SCORE_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    "ERR_DISBURSEMENT_NOT_FOUND": 404,
    "ERR_RENEWAL_NOT_FOUND": 404,
    "ERR_STEWARDSHIP_NOT_FOUND": 404,
    # Fund state
    "ERR_FUND_NOT_OPEN": 409,
    "ERR_FUND_NOT_IN_REVIEW": 409,
    "ERR_FUND_NOT_AWARDING": 409,
    "ERR_FUND_STATE_INVALID": 409,
    "ERR_CRITERIA_REQUIRED": 409,
    "ERR_DUPLICATE_CRITERIA": 409,
    "ERR_OPEN_APPLICATIONS_EXIST": 409,
    # Application state / constraints
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_RECOMMENDATION_REQUIRED": 409,
    "ERR_TRANSCRIPT_REQUIRED": 409,
    "ERR_DUPLICATE_TRANSCRIPT": 409,
    "ERR_NOT_ELIGIBLE": 409,
    "ERR_NO_COMMITTEE_ASSIGNED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    # Committee / scoring
    "ERR_ASSIGNMENT_STATE_INVALID": 409,
    "ERR_MEMBER_OVERLOADED": 409,
    "ERR_DUPLICATE_ASSIGNMENT": 409,
    "ERR_SCORE_STATE_INVALID": 409,
    "ERR_APPLICATION_NOT_UNDER_REVIEW": 409,
    "ERR_NO_ASSIGNMENT_FOR_SCORE": 409,
    "ERR_QUORUM_NOT_MET": 409,
    # Award / disbursement / renewal / stewardship
    "ERR_SCORE_BELOW_FLOOR": 409,
    "ERR_AWARD_STATE_INVALID": 409,
    "ERR_AWARD_NOT_ACTIVE": 409,
    "ERR_AWARD_ALREADY_DISBURSED": 409,
    "ERR_STEWARDSHIP_REQUIRED": 409,
    "ERR_STEWARDSHIP_STATE_INVALID": 409,
    "ERR_DISBURSEMENT_STATE_INVALID": 409,
    "ERR_GPA_BELOW_FLOOR": 409,
    # Fiscal / concurrency
    "ERR_FUND_INSUFFICIENT": 409,
    "ERR_STALE_FUND_VERSION": 412,
    # Input
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
}


def err(error_id, message=None):
    """Construct an ApiError using the canonical HTTP status for the id."""
    return ApiError(error_id, ERROR_HTTP.get(error_id, 400), message)

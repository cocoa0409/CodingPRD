"""Error catalogue (PRD section 5)."""

ERROR_STATUS = {
    # authentication / authorization / identity
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ELECTOR_IDENTITY_UNKNOWN": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_CANDIDATE_NOT_FOUND": 404,
    "ERR_CANDIDACY_NOT_FOUND": 404,
    "ERR_ELECTOR_NOT_FOUND": 404,
    "ERR_BALLOT_NOT_FOUND": 404,
    "ERR_INDUCTION_NOT_FOUND": 404,
    "ERR_EXHIBIT_NOT_FOUND": 404,
    "ERR_ELIGIBILITY_RULE_NOT_FOUND": 404,
    "ERR_BLOC_NOT_FOUND": 404,
    # state preconditions
    "ERR_INVALID_CYCLE_STATE": 409,
    "ERR_INVALID_CANDIDACY_STATE": 409,
    "ERR_INVALID_ELECTOR_STATE": 409,
    "ERR_INVALID_BALLOT_STATE": 409,
    "ERR_BALLOT_EXPIRED": 409,
    "ERR_INVALID_TALLY_STATE": 409,
    "ERR_ELECTION_NOT_FINAL": 409,
    "ERR_CEREMONY_NOT_PLANNED": 409,
    "ERR_INVALID_GRANT_STATE": 409,
    "ERR_INVALID_INDUCTION_STATE": 409,
    # optimistic concurrency
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_STALE_BALLOT_VERSION": 412,
    # duty and credential compliance
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOMINATOR_IDENTITY_MISMATCH": 403,
    "ERR_NOT_SCREENING_MEMBER": 403,
    "ERR_ELECTOR_NOT_CREDENTIALED": 403,
    "ERR_CREDENTIAL_EXPIRED": 403,
    # eligibility and quota
    "ERR_CANDIDATE_INELIGIBLE": 422,
    "ERR_POSTHUMOUS_PATHWAY_REQUIRES_DECEASED": 422,
    "ERR_WAITING_PERIOD_NOT_MET": 422,
    "ERR_CAREER_THRESHOLD_NOT_MET": 422,
    "ERR_APPEARANCE_LIMIT_REACHED": 422,
    "ERR_JUSTIFICATION_REQUIRED": 422,
    "ERR_SPECIAL_ELECTION_QUOTA_EXHAUSTED": 409,
    "ERR_DUPLICATE_CANDIDACY": 409,
    # uniqueness and quantitative constraints
    "ERR_DUPLICATE_SUBMISSION": 409,
    "ERR_DUPLICATE_CONFIGURATION": 409,
    "ERR_INFO_REQUEST_LIMIT": 409,
    "ERR_BLOC_SEATS_EXHAUSTED": 409,
    "ERR_NO_SLATE_AVAILABLE": 409,
    "ERR_MAX_VOTES_EXCEEDED": 422,
    "ERR_NO_BALLOTS_CAST": 409,
    "ERR_BLOC_QUORUM_NOT_MET": 409,
    "ERR_CASE_CAPACITY_EXCEEDED": 409,
    "ERR_ESCORT_POOL_EXHAUSTED": 409,
    "ERR_INDUCTIONS_NOT_READY": 409,
    # temporal
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_VOTING_WINDOW_CLOSED": 409,
    "ERR_INVALID_ESCORT_INTERVAL": 422,
    "ERR_CASE_WINDOW_CONFLICT": 409,
    "ERR_CEREMONY_DATE_NOT_REACHED": 409,
    # referential and fiscal
    "ERR_SLOT_NOT_ON_BALLOT": 422,
    "ERR_SLOT_STRUCK": 409,
    "ERR_INDUCTION_CYCLE_MISMATCH": 422,
    "ERR_ARTIFACTS_NOT_RECEIVED": 409,
    "ERR_TRAVEL_BUDGET_EXCEEDED": 409,
    # framework-level fallbacks
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)

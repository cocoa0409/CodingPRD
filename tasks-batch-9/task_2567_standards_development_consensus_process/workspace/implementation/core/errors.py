"""Error catalogue (59 error ids) and the ApiError exception."""

# --- HTTP status per error id -------------------------------------------------
ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_COMMITTEE_CHAIR": 403,
    "ERR_NOT_VOTE_OWNER": 403,
    "ERR_ACTOR_IDENTITY_MISMATCH": 403,
    "ERR_SELF_ADJUDICATION": 403,
    "ERR_DISPOSITION_APPROVER_CONFLICT": 403,
    "ERR_APPELLANT_NOT_INTERESTED_PARTY": 403,
    # existence
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_COMMITTEE_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_WORK_ITEM_NOT_FOUND": 404,
    "ERR_DRAFT_NOT_FOUND": 404,
    "ERR_BALLOT_NOT_FOUND": 404,
    "ERR_VOTE_NOT_FOUND": 404,
    "ERR_COMMENT_NOT_FOUND": 404,
    "ERR_PUBLIC_REVIEW_NOT_FOUND": 404,
    "ERR_PATENT_DISCLOSURE_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_MAINTENANCE_ITEM_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_NEGATIVE_REQUIRES_COMMENT": 400,
    # state
    "ERR_INVALID_DRAFT_STATE": 409,
    "ERR_INVALID_WORK_ITEM_STATE": 409,
    "ERR_BALLOT_NOT_OPEN": 409,
    "ERR_INVALID_PUBLIC_REVIEW_STATE": 409,
    "ERR_INVALID_COMMENT_STATE": 409,
    "ERR_INVALID_APPEAL_STATE": 409,
    "ERR_INVALID_MAINTENANCE_STATE": 409,
    "ERR_VOTE_NOT_ADJUDICABLE": 409,
    "ERR_COMMITTEE_NOT_ACTIVE": 409,
    "ERR_STANDARD_NOT_PUBLISHED": 409,
    "ERR_INVALID_COMMITTEE_STATE": 409,
    # optimistic concurrency
    "ERR_STALE_DRAFT_VERSION": 412,
    "ERR_STALE_WORK_ITEM_VERSION": 412,
    # consensus / due process
    "ERR_NEGATIVES_NOT_CONSIDERED": 409,
    "ERR_CONSENSUS_GATE_BLOCKED": 409,
    "ERR_IP_NOT_CLEARED": 409,
    "ERR_PUBLIC_REVIEW_NOT_APPROVED": 409,
    "ERR_DISPOSITION_INCOMPLETE": 409,
    # business rules
    "ERR_COMMITTEE_NOT_BALANCED": 409,
    "ERR_CHAIR_NOT_MEMBER": 409,
    "ERR_DUPLICATE_MEMBERSHIP": 409,
    "ERR_AFFILIATION_ALREADY_REPRESENTED": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_VOTER_NOT_ELIGIBLE": 409,
    "ERR_BALLOT_CAPACITY_EXCEEDED": 409,
    "ERR_MAINTENANCE_ACTION_MISMATCH": 409,
    "ERR_REAFFIRMATION_BALLOT_REQUIRED": 409,
    # temporal
    "ERR_BALLOT_WINDOW_TOO_SHORT": 409,
    "ERR_BALLOT_NOT_ENDED": 409,
    "ERR_BALLOT_NOT_IN_VOTING_WINDOW": 409,
    "ERR_REVIEW_PERIOD_TOO_SHORT": 409,
    "ERR_REVIEW_NOT_ENDED": 409,
    "ERR_REVIEW_WINDOW_BUFFER_CONFLICT": 409,
    "ERR_APPEAL_ANCHOR_MISSING": 409,
    "ERR_APPEAL_UNTIMELY": 409,
    "ERR_PERIODIC_REVIEW_NOT_DUE": 409,
    "ERR_REAFFIRMATION_WINDOW_EXPIRED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty.",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are malformed.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalogue error."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def bad_request(message="The request body or query parameters are malformed."):
    raise ApiError("ERR_INVALID_REQUEST", message)


# Existence error id per collection name, used for path + body FK resolution.
NOT_FOUND_ERROR = {
    "participants": "ERR_PARTICIPANT_NOT_FOUND",
    "committees": "ERR_COMMITTEE_NOT_FOUND",
    "memberships": "ERR_MEMBERSHIP_NOT_FOUND",
    "work_items": "ERR_WORK_ITEM_NOT_FOUND",
    "drafts": "ERR_DRAFT_NOT_FOUND",
    "ballots": "ERR_BALLOT_NOT_FOUND",
    "votes": "ERR_VOTE_NOT_FOUND",
    "comments": "ERR_COMMENT_NOT_FOUND",
    "public_reviews": "ERR_PUBLIC_REVIEW_NOT_FOUND",
    "patent_disclosures": "ERR_PATENT_DISCLOSURE_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
    "maintenance_items": "ERR_MAINTENANCE_ITEM_NOT_FOUND",
}

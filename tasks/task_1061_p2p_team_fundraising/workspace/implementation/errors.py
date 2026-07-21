"""Error catalogue (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_TEAM_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_DONOR_NOT_FOUND": 404,
    "ERR_DONATION_NOT_FOUND": 404,
    "ERR_MATCH_POOL_NOT_FOUND": 404,
    "ERR_TIER_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    "ERR_RECEIPT_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DONATION_NOT_REFUNDABLE": 409,
    "ERR_REFUND_WINDOW_EXPIRED": 422,
    "ERR_CAMPAIGN_NOT_PUBLISHED": 409,
    "ERR_PARTICIPANT_NOT_ACTIVE": 409,
    "ERR_DESIGNATION_UNRESOLVABLE": 422,
    "ERR_EVENT_CAMPAIGN_MISMATCH": 422,
    "ERR_TEAM_CAMPAIGN_MISMATCH": 422,
    "ERR_SELF_RECRUIT": 422,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_REGISTRATION_TIME_CONFLICT": 409,
    "ERR_EVENT_AT_CAPACITY": 422,
    "ERR_MATCH_WINDOW_OVERLAP": 409,
    "ERR_FUNDRAISING_MINIMUM_NOT_MET": 422,
    "ERR_PAYOUT_BELOW_MINIMUM": 422,
    "ERR_INSUFFICIENT_CAMPAIGN_BALANCE": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ORGANIZATION_PAYOUT_UNVERIFIED": 409,
    "ERR_STALE_CAMPAIGN_VERSION": 412,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognized.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_INVALID_STATE": "The target resource is not in a state that admits this transition.",
    "ERR_DONATION_NOT_REFUNDABLE": "Only a settled gift may be refunded.",
    "ERR_REFUND_WINDOW_EXPIRED": "The refund window for this gift has expired.",
    "ERR_CAMPAIGN_NOT_PUBLISHED": "The campaign is not published.",
    "ERR_PARTICIPANT_NOT_ACTIVE": "The fundraiser page is not active.",
    "ERR_DESIGNATION_UNRESOLVABLE": "The designation target cannot be resolved inside the campaign.",
    "ERR_EVENT_CAMPAIGN_MISMATCH": "The event and the fundraiser belong to different campaigns.",
    "ERR_TEAM_CAMPAIGN_MISMATCH": "The team belongs to a different campaign.",
    "ERR_SELF_RECRUIT": "The recruiter reference is invalid.",
    "ERR_DUPLICATE_REGISTRATION": "The fundraiser already holds an open registration for this event.",
    "ERR_REGISTRATION_TIME_CONFLICT": "The fundraiser already holds an overlapping registration.",
    "ERR_EVENT_AT_CAPACITY": "The event is at capacity.",
    "ERR_MATCH_WINDOW_OVERLAP": "The match pool window overlaps an existing pool of the campaign.",
    "ERR_FUNDRAISING_MINIMUM_NOT_MET": "The fundraising minimum has not been met.",
    "ERR_PAYOUT_BELOW_MINIMUM": "The requested amount is below the disbursement floor.",
    "ERR_INSUFFICIENT_CAMPAIGN_BALANCE": "The campaign does not have enough uncommitted funds.",
    "ERR_SEGREGATION_OF_DUTIES": "The approver must differ from the reviewer.",
    "ERR_ORGANIZATION_PAYOUT_UNVERIFIED": "The beneficiary payout account is not verified.",
    "ERR_STALE_CAMPAIGN_VERSION": "The supplied campaign version is stale.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)


def raise_error(error_id, message=None):
    raise api_error(error_id, message)

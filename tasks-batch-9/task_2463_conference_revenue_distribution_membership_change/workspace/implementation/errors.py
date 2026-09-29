"""Error catalogue (PRD section 5).

Every error_id declared by the PRD maps to exactly the HTTP status the PRD
declares for it.  ``ApiError`` is the single exception type raised by every
layer of the server; ``app.py`` turns it into the error envelope described in
PRD section 2.2.
"""

# error_id -> HTTP status, taken verbatim from PRD section 5.
ERROR_STATUS = {
    # Authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_MEMBER_OWNER": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # Conference lifecycle
    "ERR_CONFERENCE_NOT_INITIALIZED": 409,
    "ERR_CONFERENCE_ALREADY_EXISTS": 409,
    # Existence
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_REVENUE_POOL_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_RUN_NOT_FOUND": 404,
    "ERR_BOWL_APPEARANCE_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_ACTION_NOT_FOUND": 404,
    "ERR_BUDGET_PROPOSAL_NOT_FOUND": 404,
    "ERR_PROTECTED_RIVALRY_NOT_FOUND": 404,
    "ERR_SCHEDULE_GAME_NOT_FOUND": 404,
    "ERR_CHAMPIONSHIP_EVENT_NOT_FOUND": 404,
    "ERR_AUDIT_REPORT_NOT_FOUND": 404,
    # Optimistic concurrency
    "ERR_STALE_POOL_VERSION": 412,
    "ERR_STALE_ACTION_VERSION": 412,
    "ERR_STALE_CONFERENCE_VERSION": 412,
    "ERR_STALE_MEMBER_VERSION": 412,
    # Uniqueness / pairing
    "ERR_DUPLICATE_INSTITUTION_CODE": 409,
    "ERR_MEMBER_PAIR_INVALID": 422,
    "ERR_DUPLICATE_RIVALRY": 409,
    "ERR_DUPLICATE_BALLOT": 409,
    # Charter window
    "ERR_CHARTER_WINDOW_CLOSED": 409,
    # Status guards
    "ERR_MEMBER_STATE_INVALID": 409,
    "ERR_POOL_STATE_INVALID": 409,
    "ERR_RUN_STATE_INVALID": 409,
    "ERR_APPEARANCE_STATE_INVALID": 409,
    "ERR_ACTION_STATE_INVALID": 409,
    "ERR_PROPOSAL_STATE_INVALID": 409,
    "ERR_GAME_STATE_INVALID": 409,
    "ERR_EVENT_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    # Governance
    "ERR_AMEND_LIMIT_REACHED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_UNITS_ALREADY_DISTRIBUTED": 409,
    # Temporal / capacity
    "ERR_MEMBER_REST_BUFFER_VIOLATION": 409,
    "ERR_VENUE_CAPACITY_EXCEEDED": 409,
    "ERR_INVALID_EFFECTIVE_YEAR": 422,
    "ERR_VENUE_NOT_HOME_VENUE": 422,
    "ERR_INVALID_EVENT_WINDOW": 422,
    # Voting
    "ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE": 409,
    # Referential preconditions
    "ERR_NO_APPROVED_BUDGET": 409,
    "ERR_BOWL_REVIEW_PENDING": 409,
    "ERR_AUDIT_REPORT_NOT_ISSUED": 409,
    "ERR_HOST_COMPLIANCE_INSUFFICIENT": 422,
    "ERR_POOL_CLOSED_TO_REVENUE": 409,
    "ERR_RECONCILIATION_IMBALANCE": 422,
    # Fiscal guards
    "ERR_RESERVE_POSTURE_FROZEN": 409,
    "ERR_AUDITED_EXPENSE_MISSING": 409,
    "ERR_EMPTY_ALLOCATION_BASIS": 422,
    "ERR_ENTRY_FEE_OUTSTANDING": 402,
    "ERR_ENTRY_FEE_OVERPAYMENT": 422,
    "ERR_RESERVE_INSUFFICIENT": 422,
}

# Default human readable messages (PRD section 5 message templates).
ERROR_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted to perform this operation.",
    "ERR_NOT_MEMBER_OWNER": "A member representative may only act on its own member record.",
    "ERR_INVALID_REQUEST": "The request body is malformed or a field failed validation.",
    "ERR_INVALID_PAGINATION": "The pagination parameters are outside the permitted range.",
    "ERR_CONFERENCE_NOT_INITIALIZED": "The conference has not been initialised.",
    "ERR_CONFERENCE_ALREADY_EXISTS": "The conference has already been initialised.",
    "ERR_VENUE_NOT_FOUND": "The requested venue does not exist.",
    "ERR_MEMBER_NOT_FOUND": "The requested member does not exist.",
    "ERR_REVENUE_POOL_NOT_FOUND": "The requested revenue pool does not exist.",
    "ERR_DISTRIBUTION_RUN_NOT_FOUND": "The requested distribution run does not exist.",
    "ERR_BOWL_APPEARANCE_NOT_FOUND": "The requested bowl appearance does not exist.",
    "ERR_MEMBERSHIP_ACTION_NOT_FOUND": "The requested membership action does not exist.",
    "ERR_BUDGET_PROPOSAL_NOT_FOUND": "The requested budget proposal does not exist.",
    "ERR_PROTECTED_RIVALRY_NOT_FOUND": "The requested protected rivalry does not exist.",
    "ERR_SCHEDULE_GAME_NOT_FOUND": "The requested schedule game does not exist.",
    "ERR_CHAMPIONSHIP_EVENT_NOT_FOUND": "The requested championship event does not exist.",
    "ERR_AUDIT_REPORT_NOT_FOUND": "The requested audit report does not exist.",
    "ERR_STALE_POOL_VERSION": "The supplied revenue pool version does not match the stored version.",
    "ERR_STALE_ACTION_VERSION": "The supplied membership action version does not match the stored version.",
    "ERR_STALE_CONFERENCE_VERSION": "The supplied conference version does not match the stored version.",
    "ERR_STALE_MEMBER_VERSION": "The supplied member version does not match the stored version.",
    "ERR_DUPLICATE_INSTITUTION_CODE": "The institution code is already in use in this conference.",
    "ERR_MEMBER_PAIR_INVALID": "The referenced member pair is invalid.",
    "ERR_DUPLICATE_RIVALRY": "A protected rivalry already exists for this pair of members.",
    "ERR_DUPLICATE_BALLOT": "This member has already cast a ballot on this vote.",
    "ERR_CHARTER_WINDOW_CLOSED": "Charter members may only be seated while the conference is FORMING.",
    "ERR_MEMBER_STATE_INVALID": "The member's status does not permit this operation.",
    "ERR_POOL_STATE_INVALID": "The revenue pool's status does not permit this operation.",
    "ERR_RUN_STATE_INVALID": "The distribution run's status does not permit this operation.",
    "ERR_APPEARANCE_STATE_INVALID": "The bowl appearance's status does not permit this operation.",
    "ERR_ACTION_STATE_INVALID": "The membership action's status does not permit this operation.",
    "ERR_PROPOSAL_STATE_INVALID": "The budget proposal's status does not permit this operation.",
    "ERR_GAME_STATE_INVALID": "The schedule game's status does not permit this operation.",
    "ERR_EVENT_STATE_INVALID": "The championship event's status does not permit this operation.",
    "ERR_REPORT_STATE_INVALID": "The audit report's status does not permit this operation.",
    "ERR_AMEND_LIMIT_REACHED": "The membership action has already been amended the maximum number of times.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not both prepare and approve this operation.",
    "ERR_UNITS_ALREADY_DISTRIBUTED": "The appearance's postseason units have already been distributed.",
    "ERR_MEMBER_REST_BUFFER_VIOLATION": "A participant already has a game inside the required rest buffer.",
    "ERR_VENUE_CAPACITY_EXCEEDED": "The venue's concurrent event capacity would be exceeded.",
    "ERR_INVALID_EFFECTIVE_YEAR": "The effective fiscal year is not permitted.",
    "ERR_VENUE_NOT_HOME_VENUE": "The venue is not the home team's home venue.",
    "ERR_INVALID_EVENT_WINDOW": "The event window is invalid.",
    "ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE": "The member carries no voting weight.",
    "ERR_NO_APPROVED_BUDGET": "No approved budget exists for the current fiscal year.",
    "ERR_BOWL_REVIEW_PENDING": "A bowl appearance for this fiscal year is still under review.",
    "ERR_AUDIT_REPORT_NOT_ISSUED": "No issued audit report exists for this distribution run.",
    "ERR_HOST_COMPLIANCE_INSUFFICIENT": "The host member's schedule compliance score is below the hosting minimum.",
    "ERR_POOL_CLOSED_TO_REVENUE": "The revenue pool is closed and cannot accept further revenue.",
    "ERR_RECONCILIATION_IMBALANCE": "The distribution run does not reconcile to zero.",
    "ERR_RESERVE_POSTURE_FROZEN": "The conference reserve posture is FROZEN.",
    "ERR_AUDITED_EXPENSE_MISSING": "The revenue pool has no audited expense recorded.",
    "ERR_EMPTY_ALLOCATION_BASIS": "The allocation basis is empty; total weight is zero.",
    "ERR_ENTRY_FEE_OUTSTANDING": "The member still owes part of its assessed entry fee.",
    "ERR_ENTRY_FEE_OVERPAYMENT": "The payment would exceed the assessed entry fee.",
    "ERR_RESERVE_INSUFFICIENT": "The reserve balance is insufficient for this withdrawal.",
}


class ApiError(Exception):
    """A refusal carrying the PRD error_id and its declared HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or ERROR_MESSAGE.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)

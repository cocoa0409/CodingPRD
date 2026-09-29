"""Error catalogue (PRD section 5 / scaffold section 1.6)."""

ERROR_HTTP = {
    # auth / authorization / request shape
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ACTOR_NOT_RECOGNIZED": 403,
    "ERR_ENTRY_NOT_OWNED": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    # existence
    "ERR_SHOW_NOT_FOUND": 404,
    "ERR_RING_NOT_FOUND": 404,
    "ERR_DIVISION_NOT_FOUND": 404,
    "ERR_CLASS_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_OFFICIAL_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_RIDER_NOT_FOUND": 404,
    "ERR_HORSE_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_CLASS_ENTRY_NOT_FOUND": 404,
    "ERR_POINT_SUBMISSION_NOT_FOUND": 404,
    "ERR_COMPLIANCE_CASE_NOT_FOUND": 404,
    "ERR_COVERAGE_SHIFT_NOT_FOUND": 404,
    # state preconditions
    "ERR_SHOW_LICENSE_NOT_DRAFT": 409,
    "ERR_SHOW_LICENSE_NOT_SUBMITTED": 409,
    "ERR_SHOW_LICENSE_NOT_APPROVED": 409,
    "ERR_SHOW_LICENSE_LOCKED": 409,
    "ERR_CLASS_NOT_PLANNED": 409,
    "ERR_CLASS_NOT_OPEN": 409,
    "ERR_CLASS_ALREADY_SCHEDULED": 409,
    "ERR_CLASS_NOT_IN_PROGRESS": 409,
    "ERR_CLASS_NOT_JUDGED": 409,
    "ERR_CLASS_RESULTS_NOT_POSTED": 409,
    "ERR_SLOT_NOT_SCHEDULED": 409,
    "ERR_RING_NOT_AVAILABLE": 409,
    "ERR_ENTRY_NOT_RECEIVED": 409,
    "ERR_ENTRY_NOT_VERIFIED": 409,
    "ERR_ENTRY_ALREADY_INVOICED": 409,
    "ERR_ENTRY_NOT_INVOICED": 409,
    "ERR_ENTRY_ALREADY_TERMINAL": 409,
    "ERR_SUBMISSION_ALREADY_FINALIZED": 409,
    "ERR_CASE_ALREADY_ADJUDICATED": 409,
    "ERR_COVERAGE_SHIFT_NOT_SCHEDULED": 409,
    # safety / welfare / compliance
    "ERR_RIDER_MEMBERSHIP_LAPSED": 422,
    "ERR_COGGINS_EXPIRED": 422,
    "ERR_HORSE_SUSPENDED": 422,
    "ERR_OFFICIAL_LICENSE_INSUFFICIENT": 422,
    "ERR_FOOTING_UNSAFE": 422,
    "ERR_VET_COVERAGE_MISSING": 422,
    "ERR_OFFICIALS_REQUIREMENT_UNMET": 422,
    "ERR_WELFARE_STRIKE_LIMIT": 409,
    # referential / integrity
    "ERR_OFFICIAL_CONFLICT_OF_INTEREST": 409,
    "ERR_JUDGE_NOT_ASSIGNED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_QUALIFIER_CYCLE": 409,
    # temporal
    "ERR_ENTRY_WINDOW_CLOSED": 409,
    "ERR_SLOT_OUTSIDE_SHOW_WINDOW": 409,
    "ERR_RING_SLOT_OVERLAP": 409,
    "ERR_OFFICIAL_TIME_CONFLICT": 409,
    # constraint
    "ERR_JUMP_HEIGHT_OUT_OF_RANGE": 422,
    "ERR_CLASS_NUMBER_DUPLICATE": 409,
    "ERR_DIVISION_SHARE_OVERSUBSCRIBED": 422,
    "ERR_CLASS_FULL": 409,
    "ERR_DUPLICATE_CLASS_ENTRY": 409,
    "ERR_OFFICIAL_LOAD_EXCEEDED": 409,
    "ERR_NO_ENTRIES_TO_JUDGE": 409,
    "ERR_INVALID_PLACINGS": 422,
    "ERR_CLASS_NOT_POINT_ELIGIBLE": 409,
    "ERR_CLASS_LIST_INCOMPLETE": 422,
    "ERR_FINDING_NOT_APPLICABLE": 422,
    "ERR_COVERAGE_CHECKIN_TOO_EARLY": 409,
    # fiscal
    "ERR_STALL_CAPACITY_EXCEEDED": 409,
    "ERR_PRIZE_POOL_EXCEEDED": 409,
    "ERR_UNPAID_PLACED_ENTRY": 402,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to perform this operation.",
    "ERR_ACTOR_NOT_RECOGNIZED": "X-User-ID does not resolve to an existing actor for this role.",
    "ERR_ENTRY_NOT_OWNED": "The acting exhibitor does not own this entry.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)

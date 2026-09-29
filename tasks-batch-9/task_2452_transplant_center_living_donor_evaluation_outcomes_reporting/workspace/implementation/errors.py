"""Error catalogue -- error_id -> HTTP status, exactly as declared in the spec."""

ERROR_STATUS = {
    # auth
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_ASSIGNED_ADVOCATE": 403,
    "ERR_NOT_ASSIGNED_REVIEWER": 403,
    # request shape
    "ERR_VALIDATION": 400,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_RECIPIENT_NOT_FOUND": 404,
    "ERR_DONOR_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_CHAIN_NOT_FOUND": 404,
    "ERR_SEGMENT_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_FOLLOW_UP_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_CHAIN_VERSION": 412,
    "ERR_STALE_REVIEW_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CHAIN_NOT_COMMITTED": 409,
    "ERR_REVIEW_NOT_FINALIZED": 409,
    "ERR_CLAIM_NOT_ADJUDICATED": 409,
    "ERR_BOOKING_NOT_ACTIVE": 409,
    "ERR_FOLLOW_UP_TERMINAL": 409,
    # business rules
    "ERR_STAFF_ROLE_INVALID": 422,
    "ERR_ADVOCATE_CONFLICT_OF_INTEREST": 422,
    "ERR_REVIEWER_SOD_CONFLICT": 422,
    "ERR_COOLING_OFF_NOT_ELAPSED": 422,
    "ERR_CLEARANCE_INCOMPLETE": 422,
    "ERR_HARD_EXCLUSION_PRESENT": 422,
    "ERR_PROGRAM_FROZEN": 409,
    "ERR_PROGRAM_RESTRICTED": 409,
    "ERR_DONOR_NOT_APPROVED": 422,
    "ERR_RECIPIENT_NOT_ACTIVE": 422,
    "ERR_DONOR_NOT_COMMITTED": 422,
    "ERR_DONOR_NOT_DONATED": 422,
    "ERR_CROSS_PROGRAM_REFERENCE": 422,
    "ERR_CHAIN_TOO_SHORT": 422,
    "ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS": 422,
    "ERR_CHAIN_LINKAGE_BROKEN": 422,
    "ERR_DUPLICATE_PARTICIPANT": 422,
    "ERR_ABO_INCOMPATIBLE": 422,
    "ERR_LOOP_NOT_CLOSED": 422,
    "ERR_NDD_START_INVALID": 422,
    # uniqueness
    "ERR_DUPLICATE_CENTER_CODE": 409,
    "ERR_DUPLICATE_NPI": 409,
    "ERR_DUPLICATE_ROOM_CODE": 409,
    "ERR_POSITION_TAKEN": 409,
    "ERR_DUPLICATE_OPEN_EVALUATION": 409,
    "ERR_DUPLICATE_REVIEW_PERIOD": 409,
    # scheduling
    "ERR_OR_SLOT_CONFLICT": 409,
    "ERR_SURGEON_DOUBLE_BOOKED": 409,
    "ERR_DONOR_BOOKING_MISSING": 422,
    "ERR_IMPLANT_BOOKING_MISSING": 422,
    "ERR_PREDECESSOR_TIMING_INVALID": 422,
    # clock relative
    "ERR_OFFER_WINDOW_EXPIRED": 422,
    "ERR_FOLLOW_UP_NOT_DUE": 422,
    "ERR_EFFECTIVE_AT_OUT_OF_ORDER": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # limits
    "ERR_CIT_LIMIT_EXCEEDED": 422,
    "ERR_CHAIN_CIT_BUDGET_EXCEEDED": 422,
    "ERR_PLAN_NOT_REQUIRED": 422,
    "ERR_DONOR_LIFETIME_CAP_REACHED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADER": "X-User-ID or X-User-Role is absent or empty",
    "ERR_UNAUTHORIZED": "the caller is not authorized for this operation",
    "ERR_VALIDATION": "request validation failed",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower()
        )
        super().__init__(self.message)

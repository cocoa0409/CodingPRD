"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # universal ladder
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_DISTRIBUTOR_NOT_FOUND": 404,
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_BOOKING_OFFER_NOT_FOUND": 404,
    "ERR_CLEARANCE_NOT_FOUND": 404,
    "ERR_DCP_ASSET_NOT_FOUND": 404,
    "ERR_KDM_KEY_NOT_FOUND": 404,
    "ERR_SHOWTIME_NOT_FOUND": 404,
    "ERR_SPECIAL_EVENT_NOT_FOUND": 404,
    "ERR_TICKET_ORDER_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_BOOKING_VERSION": 412,
    "ERR_STALE_CLEARANCE_VERSION": 412,
    # state
    "ERR_BOOKING_INVALID_STATE": 409,
    "ERR_CLEARANCE_INVALID_STATE": 409,
    "ERR_DCP_ASSET_INVALID_STATE": 409,
    "ERR_KDM_KEY_INVALID_STATE": 409,
    "ERR_SHOWTIME_INVALID_STATE": 409,
    "ERR_SPECIAL_EVENT_INVALID_STATE": 409,
    "ERR_TICKET_ORDER_INVALID_STATE": 409,
    "ERR_MEMBER_INVALID_STATE": 409,
    "ERR_SETTLEMENT_INVALID_STATE": 409,
    # rights and technical safety
    "ERR_CLEARANCE_NOT_CLEARED": 422,
    "ERR_CLEARANCE_WINDOW_NOT_COVERED": 422,
    "ERR_SCREENING_ALLOWANCE_EXHAUSTED": 422,
    "ERR_FORMAT_INCOMPATIBLE": 422,
    "ERR_DEPENDENCY_STATE_INVALID": 422,
    "ERR_NO_COVERING_KDM": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # temporal and resource geometry
    "ERR_SCREEN_SLOT_CONFLICT": 409,
    "ERR_KDM_WINDOW_OVERLAP": 409,
    "ERR_INGEST_LANE_CAPACITY_EXCEEDED": 409,
    "ERR_SHOWTIME_WINDOW_INVALID": 422,
    "ERR_ADVANCE_ACCESS_NOT_OPEN": 422,
    "ERR_OFFER_EXPIRED": 422,
    # constraint
    "ERR_INSUFFICIENT_SEATS": 422,
    "ERR_COMP_ALLOWANCE_EXCEEDED": 422,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 422,
    "ERR_WEEKLY_BALANCE_EXCEEDED": 422,
    "ERR_NO_ELIGIBLE_SLOT": 422,
    "ERR_MEMBER_EMAIL_TAKEN": 409,
    "ERR_REFERENCE_MISMATCH": 422,
    # fiscal
    "ERR_SHOWTIME_SALES_CLOSED": 422,
    "ERR_SETTLEMENT_NOT_PERMITTED": 422,
    "ERR_CREDIT_BALANCE_INSUFFICIENT": 422,
    "ERR_HOUSE_NUT_ABOVE_CAP": 422,
    "ERR_GUARANTEE_REQUIRED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication role header is missing or names an undeclared role.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not permitted on this endpoint.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)

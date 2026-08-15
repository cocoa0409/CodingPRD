"""Error catalogue (PRD section 5 / SCAFFOLD 1.6) and the carrying exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_DURATION_OUT_OF_RANGE": 422,
    "ERR_SERVICE_WINDOW_OUT_OF_RANGE": 422,
    "ERR_BLOCK_WINDOW_OUT_OF_TERM": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_INSURANCE_INVALID": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ORG_SUSPENDED": 409,
    "ERR_TERM_PRIORITY_LOCKED": 409,
    "ERR_CONFIRM_WINDOW_EXPIRED": 409,
    "ERR_CHECKIN_WINDOW_CLOSED": 409,
    "ERR_ROOM_NOT_AVAILABLE": 409,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_FEATURE_MISMATCH": 422,
    "ERR_CREW_CATEGORY_MISMATCH": 422,
    "ERR_CREW_SHIFT_MISMATCH": 422,
    "ERR_CREW_CAPACITY_EXCEEDED": 409,
    "ERR_NO_KEYS_AVAILABLE": 409,
    "ERR_ACCESS_GRANTS_OUTSTANDING": 409,
    "ERR_ROOM_EDIT_BLOCKED": 409,
    "ERR_ROOM_BLOCKED": 409,
    "ERR_TERM_ALREADY_FINALIZED": 409,
    "ERR_PREPAYMENT_REQUIRED": 402,
    "ERR_OVERPAYMENT": 422,
    "ERR_REFUND_EXCEEDS_PAID": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role or X-User-ID is missing, or the role is unrecognized.",
    "ERR_FORBIDDEN": "The acting role may not call this endpoint.",
    "ERR_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request payload is malformed: a required field is missing, or a value has a bad type or enum.",
    "ERR_INVALID_TIME_RANGE": "The end of the range is not later than its start.",
    "ERR_DURATION_OUT_OF_RANGE": "The event duration is outside [30 minutes, 8 hours].",
    "ERR_SERVICE_WINDOW_OUT_OF_RANGE": "The service window is not within [event.start_at - 2h, event.end_at + 2h].",
    "ERR_BLOCK_WINDOW_OUT_OF_TERM": "The block window is malformed or produces no instance inside the term dates.",
    "ERR_STALE_VERSION": "The expected version does not match the parent's current version.",
    "ERR_INVALID_STATE": "The target resource is not in a valid from-state for the requested transition.",
    "ERR_INSURANCE_INVALID": "External-client insurance is not valid through the event end with sufficient coverage.",
    "ERR_SEGREGATION_OF_DUTIES": "The waiving operator must differ from the event's approver.",
    "ERR_ORG_SUSPENDED": "The organization is suspended.",
    "ERR_TERM_PRIORITY_LOCKED": "The term is in its academic priority scheduling window.",
    "ERR_CONFIRM_WINDOW_EXPIRED": "The confirmation deadline has passed.",
    "ERR_CHECKIN_WINDOW_CLOSED": "Check-in is outside [start_at - 30m, start_at + 15m].",
    "ERR_ROOM_NOT_AVAILABLE": "The room has an occupancy, placed-block, or outage conflict.",
    "ERR_CAPACITY_EXCEEDED": "The attendance or enrollment exceeds the room capacity.",
    "ERR_FEATURE_MISMATCH": "The required features are not a subset of the room's features.",
    "ERR_CREW_CATEGORY_MISMATCH": "The crew's category differs from the order's category.",
    "ERR_CREW_SHIFT_MISMATCH": "The crew's shift does not cover the full service window.",
    "ERR_CREW_CAPACITY_EXCEEDED": "The crew's concurrent capacity would be exceeded.",
    "ERR_NO_KEYS_AVAILABLE": "No physical key slots remain for the room.",
    "ERR_ACCESS_GRANTS_OUTSTANDING": "The event holds issued or overdue access grants.",
    "ERR_ROOM_EDIT_BLOCKED": "The capacity reduction would leave a confirmed or in-progress event over capacity.",
    "ERR_ROOM_BLOCKED": "The outage window overlaps a non-bumpable event.",
    "ERR_TERM_ALREADY_FINALIZED": "Another finalized scheduling run already exists for the term.",
    "ERR_PREPAYMENT_REQUIRED": "A probationary organization must fully cover the provisional invoice before confirming.",
    "ERR_OVERPAYMENT": "The payment or waiver exceeds the remaining balance.",
    "ERR_REFUND_EXCEEDS_PAID": "The refund exceeds what was actually paid.",
}

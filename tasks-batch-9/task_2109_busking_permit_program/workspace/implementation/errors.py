"""Error type and the complete error catalogue (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_PITCH_NOT_FOUND": 404,
    "ERR_PERFORMER_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_AUDITION_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_DRAW_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_CLOSURE_NOT_FOUND": 404,
    "ERR_ZONE_CODE_TAKEN": 409,
    "ERR_PITCH_CODE_TAKEN": 409,
    "ERR_PERFORMER_EMAIL_TAKEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_PERMIT_NOT_ACTIVE": 409,
    "ERR_PERMIT_SUSPENDED": 409,
    "ERR_COMPLAINT_ALREADY_RESOLVED": 409,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_PERMIT_VERSION": 412,
    "ERR_AUDITION_REQUIRED": 409,
    "ERR_AUDITION_PANEL_INCOMPLETE": 409,
    "ERR_DUPLICATE_PANEL_SCORE": 409,
    "ERR_DUPLICATE_ACTIVE_APPLICATION": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_PERFORMER_BARRED": 409,
    "ERR_AMPLIFICATION_PROHIBITED": 422,
    "ERR_AMPLIFICATION_NOT_ENDORSED": 422,
    "ERR_QUIET_HOURS_VIOLATION": 422,
    "ERR_PITCH_CLOSED": 409,
    "ERR_PITCH_ZONE_MISMATCH": 422,
    "ERR_BOOKING_PERMIT_MISMATCH": 422,
    "ERR_SESSION_TOO_LONG": 422,
    "ERR_BOOKING_LEAD_TIME": 422,
    "ERR_BOOKING_HORIZON_EXCEEDED": 422,
    "ERR_READING_OUTSIDE_SESSION": 422,
    "ERR_SESSION_ALREADY_STARTED": 409,
    "ERR_PITCH_SLOT_OVERLAP": 409,
    "ERR_PITCH_DAILY_CAP_REACHED": 409,
    "ERR_CLOSURE_WINDOW_CONFLICT": 409,
    "ERR_PITCH_NOT_PREMIUM": 422,
    "ERR_ENTRY_DEADLINE_PASSED": 409,
    "ERR_ENTRY_DEADLINE_NOT_PASSED": 409,
    "ERR_DUPLICATE_LOTTERY_ENTRY": 409,
    "ERR_NO_ELIGIBLE_ENTRIES": 409,
    "ERR_INVOICE_PAST_DUE": 402,
    "ERR_OUTSTANDING_INVOICE": 402,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_RENEWAL_WINDOW_CLOSED": 422,
    "ERR_RENEWAL_CONDUCT_INSUFFICIENT": 422,
    "ERR_SEASON_MINUTE_CAP_EXCEEDED": 409,
}

# Not-found error per collection, used for path ids and for body foreign keys.
NOT_FOUND = {
    "zones": "ERR_ZONE_NOT_FOUND",
    "pitches": "ERR_PITCH_NOT_FOUND",
    "performers": "ERR_PERFORMER_NOT_FOUND",
    "applications": "ERR_APPLICATION_NOT_FOUND",
    "auditions": "ERR_AUDITION_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "draws": "ERR_DRAW_NOT_FOUND",
    "entries": "ERR_ENTRY_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
    "closures": "ERR_CLOSURE_NOT_FOUND",
}


def raise_err(error_id, message=""):
    raise ApiError(error_id, message or error_id, ERROR_HTTP[error_id])


def invalid_request(message="The request body is malformed"):
    raise_err("ERR_INVALID_REQUEST", message)


def invalid_state(message="The requested transition is not declared from the current state"):
    raise_err("ERR_INVALID_STATE", message)


def not_found(store, message=""):
    raise_err(NOT_FOUND[store], message or "%s: row not found" % store)

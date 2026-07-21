"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_VALIDATION": 400,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_TICKET_TYPE_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_TRACK_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_SPEAKER_NOT_FOUND": 404,
    "ERR_SESSION_SPEAKER_NOT_FOUND": 404,
    "ERR_BROADCAST_NOT_FOUND": 404,
    "ERR_RECORDING_NOT_FOUND": 404,
    "ERR_SPONSOR_NOT_FOUND": 404,
    "ERR_BOOTH_NOT_FOUND": 404,
    "ERR_LEAD_NOT_FOUND": 404,
    "ERR_MATCH_REQUEST_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    "ERR_TIME_RANGE_INVALID": 422,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_STALE_EVENT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_EVENT_NOT_OPEN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CONSENT_REQUIRED": 422,
    "ERR_GATING_NOT_PERMITTED": 403,
    "ERR_REGISTRATION_EVENT_MISMATCH": 422,
    "ERR_CONTRACT_NOT_SIGNED": 409,
    "ERR_SELF_MATCH_NOT_ALLOWED": 422,
    "ERR_DUPLICATE_LEAD": 409,
    "ERR_TRACK_SLOT_CONFLICT": 409,
    "ERR_SPEAKER_BUFFER_CONFLICT": 409,
    "ERR_MEETING_WINDOW_CONFLICT": 409,
    "ERR_MATCH_REQUEST_EXPIRED": 409,
    "ERR_SETTLEMENT_EXISTS": 409,
    "ERR_TICKET_SOLD_OUT": 409,
    "ERR_EVENT_CAPACITY_EXCEEDED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_UNAUTHORIZED": "The acting role may not call this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own this resource.",
    "ERR_VALIDATION": "The request body or query string failed validation.",
    "ERR_TIME_RANGE_INVALID": "The supplied interval is not well formed.",
    "ERR_DUPLICATE_REGISTRATION": "A registration with this attendee_email already exists for the event.",
    "ERR_STALE_EVENT_VERSION": "expected_event_version does not match the event's current version.",
    "ERR_INVALID_STATE": "The requested transition is not permitted from the current state.",
    "ERR_ALREADY_TERMINAL": "The resource is already in a terminal state.",
    "ERR_EVENT_NOT_OPEN": "Registration is not open for this event.",
    "ERR_SEGREGATION_OF_DUTIES": "The payer must differ from the issuer.",
    "ERR_CONSENT_REQUIRED": "Marketing consent is required to capture a lead.",
    "ERR_GATING_NOT_PERMITTED": "On-demand viewing is not permitted for this registration.",
    "ERR_REGISTRATION_EVENT_MISMATCH": "The registration belongs to a different event.",
    "ERR_CONTRACT_NOT_SIGNED": "The sponsor's contract is not signed.",
    "ERR_SELF_MATCH_NOT_ALLOWED": "A registration may not propose a meeting with itself.",
    "ERR_DUPLICATE_LEAD": "A lead already exists for this booth and registration.",
    "ERR_TRACK_SLOT_CONFLICT": "The session conflicts with another scheduled session on the track.",
    "ERR_SPEAKER_BUFFER_CONFLICT": "The session conflicts with another accepted engagement of this speaker.",
    "ERR_MEETING_WINDOW_CONFLICT": "The meeting window conflicts with an accepted meeting.",
    "ERR_MATCH_REQUEST_EXPIRED": "The match request has expired.",
    "ERR_SETTLEMENT_EXISTS": "An EVENT settlement already exists for this event.",
    "ERR_TICKET_SOLD_OUT": "The ticket type is sold out.",
    "ERR_EVENT_CAPACITY_EXCEEDED": "The event is at capacity.",
    "ERR_PAYMENT_AMOUNT_MISMATCH": "The submitted amount does not match the amount owed.",
}

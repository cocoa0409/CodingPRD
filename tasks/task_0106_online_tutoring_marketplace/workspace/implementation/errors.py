"""Error definitions for the tutoring marketplace API."""

ERROR_HTTP_STATUS = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_AUTHORIZED_FOR_RESOURCE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_SESSION_OVERLAP": 409,
    "ERR_TRIAL_ALREADY_USED": 422,
    "ERR_DISPUTE_ALREADY_OPEN": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_AMOUNT_OUT_OF_RANGE": 422,
    "ERR_TUTOR_NOT_VERIFIED": 422,
    "ERR_SUBJECT_NOT_OFFERED": 422,
    "ERR_SEGREGATION_VIOLATION": 403,
    "ERR_MINOR_REQUIRES_PARENT": 403,
    "ERR_INVALID_SESSION_WINDOW": 422,
    "ERR_CHILD_LIMIT_EXCEEDED": 422,
    "ERR_PAYOUT_STALE": 409,
    "ERR_CREDIT_APPLY_INVALID": 422,
    "ERR_ESCALATION_NOT_ALLOWED": 422,
    "ERR_ADJUSTED_MINUTES_OUT_OF_RANGE": 422,
    "ERR_VALIDATION": 400,
}


class APIError(Exception):
    """Domain exception carrying an error_id, message and HTTP status."""

    def __init__(self, error_id, message=None):
        if error_id not in ERROR_HTTP_STATUS:
            # Should never happen — guard against typos
            raise ValueError(f"Unknown error_id: {error_id}")
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message or self._default_message(error_id)
        super().__init__(self.message)

    @staticmethod
    def _default_message(error_id):
        return {
            "ERR_AUTH_REQUIRED": "Authentication headers missing or invalid.",
            "ERR_FORBIDDEN": "Role lacks permission for this endpoint.",
            "ERR_NOT_AUTHORIZED_FOR_RESOURCE": "Caller does not own this resource.",
            "ERR_NOT_FOUND": "Resource not found.",
            "ERR_INVALID_STATE": "Operation is not legal in current state.",
            "ERR_VERSION_CONFLICT": "Supplied version does not match current version.",
            "ERR_SESSION_OVERLAP": "Session overlaps with another for the same tutor.",
            "ERR_TRIAL_ALREADY_USED": "A trial session already exists for this tutor-student pair.",
            "ERR_DISPUTE_ALREADY_OPEN": "A non-terminal dispute already exists for this session.",
            "ERR_DISPUTE_WINDOW_CLOSED": "Dispute window has closed or session not eligible.",
            "ERR_AMOUNT_OUT_OF_RANGE": "Amount is outside the allowed range.",
            "ERR_TUTOR_NOT_VERIFIED": "Tutor is not in VERIFIED status.",
            "ERR_SUBJECT_NOT_OFFERED": "Subject is not in the tutor's approved tag set.",
            "ERR_SEGREGATION_VIOLATION": "Segregation of duties violated.",
            "ERR_MINOR_REQUIRES_PARENT": "Minor action requires linked parent.",
            "ERR_INVALID_SESSION_WINDOW": "Session window is invalid.",
            "ERR_CHILD_LIMIT_EXCEEDED": "Parent already manages the maximum number of children.",
            "ERR_PAYOUT_STALE": "Payout balance changed since the batch was requested.",
            "ERR_CREDIT_APPLY_INVALID": "Credit application is invalid.",
            "ERR_ESCALATION_NOT_ALLOWED": "Dispute cannot be escalated yet.",
            "ERR_ADJUSTED_MINUTES_OUT_OF_RANGE": "adjusted_minutes is outside the allowed range.",
            "ERR_VALIDATION": "Request body is malformed.",
        }.get(error_id, "Error.")

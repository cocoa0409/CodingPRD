"""Error catalogue (PRD section 5) and the ApiError exception.

Every identifier and HTTP status below is transcribed verbatim from the PRD's
error-code table; nothing is invented and nothing is defaulted.
"""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ROW_SCOPE_DENIED": 403,
    "ERR_HOUSEHOLD_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_CATALOG_ENTRY_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_ROLLOUT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_RMA_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_ACCOUNT_SUSPENDED": 403,
    "ERR_DEVICE_DECOMMISSIONED": 409,
    "ERR_TICKET_CLOSED": 409,
    "ERR_SUBSCRIPTION_CANCELLED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_SERIAL_MODEL_MISMATCH": 422,
    "ERR_SERIAL_ALREADY_CLAIMED": 409,
    "ERR_ACTIVATION_TOKEN_EXPIRED": 409,
    "ERR_ACTIVATION_ATTEMPTS_EXCEEDED": 409,
    "ERR_ACTIVATION_CODE_INVALID": 422,
    "ERR_RECLAIM_NOT_ELIGIBLE": 409,
    "ERR_RMA_IN_FLIGHT": 409,
    "ERR_OPEN_TICKET_BLOCKS_ROLLOUT": 409,
    "ERR_ROLLOUT_WINDOW_OVERLAP": 409,
    "ERR_CAMPAIGN_HALTED": 409,
    "ERR_DEFER_NOT_ALLOWED": 409,
    "ERR_RETRY_CAP_EXCEEDED": 409,
    "ERR_DISPATCH_NOT_REQUIRED": 409,
    "ERR_SLOT_REGION_MISMATCH": 422,
    "ERR_SLOT_UNAVAILABLE": 409,
    "ERR_SLOT_BUFFER_CONFLICT": 409,
    "ERR_VISIT_NOT_STARTED": 409,
    "ERR_REOPEN_WINDOW_CLOSED": 409,
    "ERR_SURVEY_ALREADY_SUBMITTED": 409,
    "ERR_SURVEY_WINDOW_CLOSED": 409,
    "ERR_ADVANCE_REPLACEMENT_NOT_ELIGIBLE": 409,
    "ERR_RETURN_WINDOW_OPEN": 409,
    "ERR_DEVICE_CAP_EXCEEDED": 409,
    "ERR_CREDIT_CAP_REACHED": 409,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by app.py."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or _DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this endpoint.",
    "ERR_ROW_SCOPE_DENIED": "The acting identity is out of scope for the target row.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_INVALID_ENUM": "A field carries a value outside its enumeration.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_INVALID_STATE": "The target row's current state does not permit this transition.",
}

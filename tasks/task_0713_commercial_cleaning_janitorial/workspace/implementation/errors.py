"""Error catalogue and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) per PRD §5.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_INVALID_RANGE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_PROPOSAL_NOT_ACCEPTED": 409,
    "ERR_BID_NOT_PRICED": 409,
    "ERR_CONTRACT_NOT_SIGNED": 409,
    "ERR_CONTRACT_NOT_SERVICING": 409,
    "ERR_STARTUP_NOT_READY": 409,
    "ERR_HOURS_UNDERALLOCATED": 409,
    "ERR_MARGIN_BELOW_FLOOR": 422,
    "ERR_BUDGET_EXCEEDED": 409,
    "ERR_CREW_UNAVAILABLE": 409,
    "ERR_OUTSIDE_AVAILABILITY": 422,
    "ERR_WALKTHROUGH_OVERLAP": 409,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_UPSELL_INVALID": 422,
    "ERR_SITE_CONTACT_MISMATCH": 409,
    "ERR_SERVICE_AREA_REQUIRED": 409,
    "ERR_VALIDATION_LIMIT": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)

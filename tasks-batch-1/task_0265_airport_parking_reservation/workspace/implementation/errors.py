"""Error catalog (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> (http_status, default message)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or unknown authentication headers."),
    "ERR_FORBIDDEN_ROLE": (403, "Acting role is not permitted for this operation."),
    "ERR_NOT_RESOURCE_OWNER": (403, "Caller does not own the target resource."),
    "ERR_NOT_FOUND": (404, "A path or referenced resource does not exist."),
    "ERR_CROSS_REFERENCE_MISMATCH": (422, "Cross-reference mismatch between supplied resources."),
    "ERR_RATE_PLAN_NOT_QUOTABLE": (422, "Rate plan is not quotable for this booking."),
    "ERR_INVALID_INTERVAL": (422, "Scheduled interval is invalid."),
    "ERR_INVALID_STATE": (409, "Requested transition is not defined from the current state."),
    "ERR_CUSTOMER_SUSPENDED": (409, "Customer account is suspended."),
    "ERR_IN_OUT_NOT_ALLOWED": (409, "In/out privileges are not allowed for this lot."),
    "ERR_STALE_LOT_VERSION": (412, "Stale lot version."),
    "ERR_STALE_SHUTTLE_VERSION": (412, "Stale shuttle trip version."),
    "ERR_NO_STALL_AVAILABLE": (409, "No stall available for the derived stall class."),
    "ERR_SHUTTLE_FULL": (409, "Shuttle trip cannot accept the assignment."),
    "ERR_VALIDATION": (400, "Malformed request body."),
}


def err(error_id, message=None):
    http_status = ERROR_CATALOG[error_id][0]
    msg = message or ERROR_CATALOG[error_id][1]
    return ApiError(error_id, http_status, msg)

"""Error definitions and the APIError exception."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> (http_status, default message)
ERRORS = {
    "ERR_AUTH_REQUIRED": (401, "Authentication headers are required."),
    "ERR_AUTH_INVALID_ROLE": (401, "Role value is not recognized."),
    "ERR_FORBIDDEN": (403, "Role is not permitted for this endpoint."),
    "ERR_RESOURCE_NOT_FOUND": (404, "Resource not found."),
    "ERR_REFERENCE_NOT_FOUND": (404, "Referenced resource not found."),
    "ERR_VALIDATION_FAILED": (400, "Field validation failed."),
    "ERR_INVALID_ASSIGNMENT_STATE": (409, "Assignment not in a valid state for this action."),
    "ERR_PAIRING_INVALID_STATE": (409, "Pairing not in a valid state for this action."),
    "ERR_INVALID_TRADE_STATE": (409, "Trade request not in a valid state for this transition."),
    "ERR_VERSION_CONFLICT": (409, "Version conflict; record has been modified."),
    "ERR_BID_WINDOW_CLOSED": (409, "Bid window has already closed."),
    "ERR_BID_WINDOW_ALREADY_AWARDED": (409, "Bid window has already been awarded."),
    "ERR_DUPLICATE_BID_PREFERENCE": (409, "Preference rank already used in this bid window."),
    "ERR_SLOT_ALREADY_COVERED": (409, "Pairing slot already has an assignment."),
    "ERR_FAA_CREW_REST_VIOLATION": (422, "FAA crew rest minimum interval not satisfied."),
    "ERR_FAA_DUTY_VIOLATION": (422, "FAA duty or block cap would be exceeded."),
    "ERR_TRADE_RULE_VIOLATION": (422, "Trade rules violated (rank/slot/union local)."),
    "ERR_RESERVE_OUTSIDE_WINDOW": (422, "Reserve callout outside standby window."),
    "ERR_NO_RESERVE_AVAILABLE": (422, "No eligible reserve crew available."),
    "ERR_BID_TOO_LATE": (422, "Bid submission after the 24h cutoff."),
    "ERR_PAIRING_INTERNAL_OVERLAP": (422, "Duty period overlap or insufficient inter-period rest."),
    "ERR_FLIGHT_LEG_INVALID": (422, "Flight leg time bounds invalid."),
    "ERR_CREW_NOT_AVAILABLE": (422, "Crew member is not available."),
}


def raise_error(error_id: str, message: str = ""):
    status, default = ERRORS.get(error_id, (500, "Internal error."))
    raise APIError(error_id, status, message or default)

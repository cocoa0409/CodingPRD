"""Error catalog: every error_id and HTTP status from PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERROR_HTTP[error_id]


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_OFFERS_NOT_OPEN": 409,
    "ERR_OFFERS_DEADLINE_PASSED": 409,
    "ERR_RETRADE_WINDOW_CLOSED": 409,
    "ERR_ENGAGEMENT_WINDOW_OVERLAP": 409,
    "ERR_ACCESS_WINDOW_OVERLAP": 409,
    "ERR_RELIST_COOLING_PERIOD": 409,
    "ERR_LOAN_LOCKED_OUT": 409,
    "ERR_BIDDER_NOT_QUALIFIED": 409,
    "ERR_PACKAGE_NOT_PUBLISHED": 409,
    "ERR_BID_NOT_SELECTED": 409,
    "ERR_ANALYSIS_NOT_APPROVED": 409,
    "ERR_HOLD_RECOMMENDED": 409,
    "ERR_NO_ACTIVE_ENGAGEMENT": 409,
    "ERR_PAYOFF_NOT_CONFIRMED": 409,
    "ERR_STATEMENT_NOT_APPROVED": 409,
    "ERR_DEPOSIT_NOT_POSTED": 409,
    "ERR_DEFEASANCE_NOT_ALLOWED": 409,
    "ERR_DATA_ROOM_LOCKED": 409,
    "ERR_PACKAGE_INCOMPLETE": 422,
    "ERR_RETRADE_CAP_EXCEEDED": 422,
    "ERR_DEPOSIT_BELOW_MINIMUM": 422,
    "ERR_INSUFFICIENT_PROOF_OF_FUNDS": 422,
    "ERR_CLAIM_EXCEEDS_AVAILABLE": 422,
    "ERR_BID_IMPROVEMENT_TOO_LOW": 422,
    "ERR_RELEASE_BLOCKED_BY_CLAIMS": 409,
    "ERR_STALE_VERSION": 412,
}


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg)


def err_forbidden(msg="Role not authorized for this operation"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg)


def err_invalid_state(msg="Invalid state transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg)


def err_segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg)

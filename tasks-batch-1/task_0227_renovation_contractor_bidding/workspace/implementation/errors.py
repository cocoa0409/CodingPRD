"""Error classes and the complete error catalog (§1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http_status
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_PROJECT_VERSION = "ERR_STALE_PROJECT_VERSION"
ERR_STALE_BID_VERSION = "ERR_STALE_BID_VERSION"
ERR_BID_DEADLINE_PASSED = "ERR_BID_DEADLINE_PASSED"
ERR_CONTRACTOR_NOT_QUALIFIED = "ERR_CONTRACTOR_NOT_QUALIFIED"
ERR_RATING_BELOW_MINIMUM = "ERR_RATING_BELOW_MINIMUM"
ERR_INCOMPLETE_SCOPE_COVERAGE = "ERR_INCOMPLETE_SCOPE_COVERAGE"
ERR_LIEN_WAIVER_REQUIRED = "ERR_LIEN_WAIVER_REQUIRED"
ERR_MILESTONE_OUT_OF_ORDER = "ERR_MILESTONE_OUT_OF_ORDER"
ERR_MILESTONE_SEQUENCE_TAKEN = "ERR_MILESTONE_SEQUENCE_TAKEN"
ERR_MILESTONE_PCT_INVALID = "ERR_MILESTONE_PCT_INVALID"
ERR_BUDGET_EXCEEDED = "ERR_BUDGET_EXCEEDED"
ERR_INSUFFICIENT_ESCROW = "ERR_INSUFFICIENT_ESCROW"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


def unauthenticated(msg=None):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg=None):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_owner(msg=None):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg=None):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg=None):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg=None):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)

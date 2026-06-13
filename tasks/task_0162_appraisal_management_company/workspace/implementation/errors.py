"""Error classes and error-ID constants from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error-ID constants (exact strings from SCAFFOLD §1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_AIR_FIREWALL_VIOLATION = "ERR_AIR_FIREWALL_VIOLATION"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_NO_ELIGIBLE_APPRAISER = "ERR_NO_ELIGIBLE_APPRAISER"
ERR_ASSIGNMENT_NOT_REVISABLE = "ERR_ASSIGNMENT_NOT_REVISABLE"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_ORDER_VERSION = "ERR_STALE_ORDER_VERSION"
ERR_APPRAISER_WINDOW_CONFLICT = "ERR_APPRAISER_WINDOW_CONFLICT"
ERR_PROPERTY_WINDOW_CONFLICT = "ERR_PROPERTY_WINDOW_CONFLICT"
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"
ERR_SECOND_REVIEW_REQUIRED = "ERR_SECOND_REVIEW_REQUIRED"
ERR_LENDER_BUDGET_EXCEEDED = "ERR_LENDER_BUDGET_EXCEEDED"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


_HTTP = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_AIR_FIREWALL_VIOLATION: 403,
    ERR_NOT_FOUND: 404,
    ERR_NO_ELIGIBLE_APPRAISER: 422,
    ERR_ASSIGNMENT_NOT_REVISABLE: 409,
    ERR_INVALID_STATE: 409,
    ERR_STALE_ORDER_VERSION: 412,
    ERR_APPRAISER_WINDOW_CONFLICT: 409,
    ERR_PROPERTY_WINDOW_CONFLICT: 409,
    ERR_INVALID_WINDOW: 422,
    ERR_SECOND_REVIEW_REQUIRED: 409,
    ERR_LENDER_BUDGET_EXCEEDED: 422,
    ERR_INVALID_REQUEST: 422,
}


def err(error_id, message=None):
    return ApiError(error_id, _HTTP[error_id], message)


def unauthenticated(msg=None):
    return err(ERR_UNAUTHENTICATED, msg)


def unauthorized(msg=None):
    return err(ERR_UNAUTHORIZED, msg)


def firewall(msg=None):
    return err(ERR_AIR_FIREWALL_VIOLATION, msg)


def not_found(msg=None):
    return err(ERR_NOT_FOUND, msg)


def invalid_state(msg=None):
    return err(ERR_INVALID_STATE, msg)


def stale_version(msg=None):
    return err(ERR_STALE_ORDER_VERSION, msg)


def invalid_request(msg=None):
    return err(ERR_INVALID_REQUEST, msg)

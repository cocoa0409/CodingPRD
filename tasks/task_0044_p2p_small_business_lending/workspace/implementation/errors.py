"""Error catalog and the ApiError exception class."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_GRADE_NOT_FUNDABLE = "ERR_GRADE_NOT_FUNDABLE"
ERR_DISCLOSURE_MISSING = "ERR_DISCLOSURE_MISSING"
ERR_LOAN_NOT_FUNDING = "ERR_LOAN_NOT_FUNDING"
ERR_FUNDING_EXCEEDED = "ERR_FUNDING_EXCEEDED"
ERR_DIVERSIFICATION_BREACH = "ERR_DIVERSIFICATION_BREACH"
ERR_PAYMENT_EXCEEDS_PAYOFF = "ERR_PAYMENT_EXCEEDS_PAYOFF"
ERR_RECOVERY_EXCEEDS_BASIS = "ERR_RECOVERY_EXCEEDS_BASIS"
ERR_LATE_FEE_NOT_DUE = "ERR_LATE_FEE_NOT_DUE"
ERR_STALE_LOAN_VERSION = "ERR_STALE_LOAN_VERSION"
ERR_INSUFFICIENT_CAPITAL = "ERR_INSUFFICIENT_CAPITAL"


def unauthenticated(msg="Missing X-User-ID or X-User-Role header."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="The caller's role is not permitted for this endpoint."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="The referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="Invalid or missing field value."):
    return ApiError(ERR_VALIDATION, 400, msg)


def invalid_state(msg="The resource is not in a state from which this transition is defined."):
    return ApiError(ERR_INVALID_STATE, 409, msg)

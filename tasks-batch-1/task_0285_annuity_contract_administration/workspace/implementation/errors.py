"""Error catalogue and the ApiError exception used throughout the service.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth / authorization ---------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"

# --- Existence --------------------------------------------------------------
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
ERR_REFERENCED_RESOURCE_NOT_FOUND = "ERR_REFERENCED_RESOURCE_NOT_FOUND"

# --- Request shape ----------------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# --- Concurrency ------------------------------------------------------------
ERR_STALE_CONTRACT_VERSION = "ERR_STALE_CONTRACT_VERSION"
ERR_STALE_EXCHANGE_VERSION = "ERR_STALE_EXCHANGE_VERSION"

# --- State / business -------------------------------------------------------
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_CONTRACT_FROZEN = "ERR_CONTRACT_FROZEN"
ERR_CREDITING_KIND_MISMATCH = "ERR_CREDITING_KIND_MISMATCH"
ERR_ALLOCATION_INCOMPLETE = "ERR_ALLOCATION_INCOMPLETE"
ERR_BENEFICIARY_SHARES_INCOMPLETE = "ERR_BENEFICIARY_SHARES_INCOMPLETE"
ERR_FUTURE_DATE_OF_DEATH = "ERR_FUTURE_DATE_OF_DEATH"
ERR_PAYOUT_OPTION_ARITY = "ERR_PAYOUT_OPTION_ARITY"
ERR_BELOW_MINIMUM_PREMIUM = "ERR_BELOW_MINIMUM_PREMIUM"
ERR_INSUFFICIENT_ACCUMULATION = "ERR_INSUFFICIENT_ACCUMULATION"
ERR_INVALID_COST_BASIS = "ERR_INVALID_COST_BASIS"
ERR_SEGMENT_TERM_OVERLAP = "ERR_SEGMENT_TERM_OVERLAP"
ERR_CREDIT_PERIOD_OVERLAP = "ERR_CREDIT_PERIOD_OVERLAP"


# Convenience constructors -------------------------------------------------
def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="The acting role is not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="The requested resource was not found."):
    return ApiError(ERR_RESOURCE_NOT_FOUND, 404, msg)


def referenced_not_found(msg="A referenced resource does not exist."):
    return ApiError(ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, msg)


def invalid_request(msg="The request is invalid."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="The requested transition is not defined from the current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)

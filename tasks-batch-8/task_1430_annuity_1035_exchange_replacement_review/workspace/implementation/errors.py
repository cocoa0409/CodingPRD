"""Error classes and error ID constants (from SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_CASE_NOT_OWNED_BY_PRODUCER = "ERR_CASE_NOT_OWNED_BY_PRODUCER"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_CONTRACT_NOT_IN_FORCE = "ERR_CONTRACT_NOT_IN_FORCE"
ERR_DUTY_SEGREGATION_VIOLATION = "ERR_DUTY_SEGREGATION_VIOLATION"
ERR_PRODUCER_SUSPENDED = "ERR_PRODUCER_SUSPENDED"
ERR_REQUIRED_DOCUMENTS_INCOMPLETE = "ERR_REQUIRED_DOCUMENTS_INCOMPLETE"
ERR_ANALYSIS_MISSING = "ERR_ANALYSIS_MISSING"
ERR_COOLING_OFF_ACTIVE = "ERR_COOLING_OFF_ACTIVE"
ERR_CONTRACT_EXCHANGED_WITHIN_12M = "ERR_CONTRACT_EXCHANGED_WITHIN_12M"
ERR_CONTRACT_EXCHANGE_IN_PROGRESS = "ERR_CONTRACT_EXCHANGE_IN_PROGRESS"
ERR_DUPLICATE_CONTRACT_NUMBER = "ERR_DUPLICATE_CONTRACT_NUMBER"
ERR_DOCUMENT_LOCKED = "ERR_DOCUMENT_LOCKED"
ERR_PARTIAL_BELOW_MINIMUM = "ERR_PARTIAL_BELOW_MINIMUM"
ERR_PARTIAL_AMOUNT_INVALID = "ERR_PARTIAL_AMOUNT_INVALID"
ERR_FREE_LOOK_EXPIRED = "ERR_FREE_LOOK_EXPIRED"
ERR_FREE_LOOK_STILL_ACTIVE = "ERR_FREE_LOOK_STILL_ACTIVE"


def missing_or_invalid_user_context():
    return ApiError(
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        "X-User-ID or X-User-Role header missing, empty, or an undeclared role",
        400,
    )


def forbidden_for_role():
    return ApiError(
        ERR_FORBIDDEN_FOR_ROLE,
        "Caller role not in the endpoint's roles list",
        403,
    )


def not_found(msg: str = "A path id or body FK does not resolve to an existing resource"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def case_not_owned():
    return ApiError(
        ERR_CASE_NOT_OWNED_BY_PRODUCER,
        "Producer-role caller attempts to mutate a case whose producer_id differs from X-User-ID",
        403,
    )


def invalid_request(msg: str = "Missing required field, invalid enum value, non-positive amount, or malformed surrender_schedule"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg: str = "Target entity is not in a state from which the requested transition is declared"):
    return ApiError(ERR_INVALID_STATE_TRANSITION, msg, 409)

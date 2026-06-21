"""Domain error classes."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_FORBIDDEN_OWNER_MISMATCH = "ERR_FORBIDDEN_OWNER_MISMATCH"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_DEADLINE_PASSED = "ERR_DEADLINE_PASSED"
ERR_ED_EXCLUSIVITY_VIOLATED = "ERR_ED_EXCLUSIVITY_VIOLATED"
ERR_APPLICATION_INCOMPLETE = "ERR_APPLICATION_INCOMPLETE"
ERR_ED_BINDING_VIOLATION = "ERR_ED_BINDING_VIOLATION"
ERR_AID_EXCEEDS_TUITION = "ERR_AID_EXCEEDS_TUITION"
ERR_YIELD_TARGET_REACHED = "ERR_YIELD_TARGET_REACHED"
ERR_WORD_COUNT_MISMATCH = "ERR_WORD_COUNT_MISMATCH"
ERR_FAFSA_DISALLOWS_ASSETS = "ERR_FAFSA_DISALLOWS_ASSETS"
ERR_PROFILE_LOCKED = "ERR_PROFILE_LOCKED"
ERR_ENROLLMENT_ALREADY_DECLARED = "ERR_ENROLLMENT_ALREADY_DECLARED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"


def unauth():
    raise APIError(ERR_UNAUTHENTICATED, 401, "Authentication required")


def forbidden_role():
    raise APIError(ERR_UNAUTHORIZED, 403, "Role not permitted for this endpoint")


def forbidden_owner():
    raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this resource")


def not_found(what: str = "resource"):
    raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")


def invalid_request(msg: str = "Invalid request"):
    raise APIError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg: str = "Invalid state for this transition"):
    raise APIError(ERR_INVALID_STATE, 409, msg)

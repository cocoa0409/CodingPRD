class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status) per PRD §5 / SCAFFOLD §1.6.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_WEEK_CLOSED = ("ERR_WEEK_CLOSED", 409)
ERR_TAP_WEEK_MISMATCH = ("ERR_TAP_WEEK_MISMATCH", 422)
ERR_BAD_VERIFICATION_TOKEN = ("ERR_BAD_VERIFICATION_TOKEN", 422)
ERR_CARD_EXPIRED = ("ERR_CARD_EXPIRED", 409)
ERR_DUPLICATE_ALLOCATION = ("ERR_DUPLICATE_ALLOCATION", 409)
ERR_FSA_CAP_EXCEEDED = ("ERR_FSA_CAP_EXCEEDED", 422)
ERR_STALE_RIDER_VERSION = ("ERR_STALE_RIDER_VERSION", 412)
ERR_INSUFFICIENT_FUNDS = ("ERR_INSUFFICIENT_FUNDS", 402)


def err(code_tuple, message=None):
    eid, status = code_tuple
    return ApiError(eid, status, message)

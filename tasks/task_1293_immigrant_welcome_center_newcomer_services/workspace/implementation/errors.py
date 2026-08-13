"""Error type carrying the scaffold error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---- catalog shortcuts -------------------------------------------------
def bad_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def unauthenticated(msg="missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="role not permitted or ownership check failed"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="resource is not in a valid state for this operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)

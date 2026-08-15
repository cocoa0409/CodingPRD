"""Error type carrying the PRD error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience constructors -------------------------------------------------

def unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not allowed on this endpoint, or ownership mismatch"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def invalid_input(msg="Missing required field, wrong type, invalid enum, or range violation"):
    return ApiError("ERR_INVALID_INPUT", 400, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def stale_version(msg="expected version does not match the resource's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def conflict(error_id, msg):
    return ApiError(error_id, 409, msg)


def unprocessable(error_id, msg):
    return ApiError(error_id, 422, msg)

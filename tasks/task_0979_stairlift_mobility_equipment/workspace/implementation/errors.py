"""Error classes carrying the exact error_id and http_status from the scaffold."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_missing_headers():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID or X-User-Role header missing or malformed")


def err_unauthorized():
    return ApiError("ERR_UNAUTHORIZED", 403,
                    "Role not permitted for this endpoint")


def err_not_found(msg="Path id or payload FK does not resolve"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Required input field missing or wrong type"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Target resource not in the required state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "expected version does not match current version")


def err_invalid_measurement(msg="Measurement out of range or geometry violated"):
    return ApiError("ERR_INVALID_MEASUREMENT", 422, msg)

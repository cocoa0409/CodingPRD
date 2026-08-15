"""API error type carrying the scaffold's exact error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---- 400 ----
def invalid_request(msg="Invalid request"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_missing_headers(msg="X-User-ID and X-User-Role headers are required and the role must be a declared role"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_invalid_request(msg="Missing required field, type mismatch, invalid enum value, or unknown field"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_time_window(msg="Minute window invalid: not 0 <= start < end <= 1439"):
    return ApiError("ERR_INVALID_TIME_WINDOW", 400, msg)

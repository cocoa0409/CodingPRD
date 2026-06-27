"""Error catalogue. Each ApiError carries an error_id, HTTP status, and message."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth ---
def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Not permitted to perform this operation."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


# --- Request validation ---
def invalid_request(msg="Request body is malformed or out of range."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- Not found ---
def not_found(error_id, msg=None):
    return ApiError(error_id, 404, msg or error_id)


# --- State (409) ---
def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg or error_id)


# --- Referential / safety (422) ---
def unprocessable(error_id, msg=None):
    return ApiError(error_id, 422, msg or error_id)


# --- Fiscal (402) ---
def guarantee_exhausted(msg="Introduction credit cost exceeds guarantee_remaining_forecast."):
    return ApiError("ERR_GUARANTEE_EXHAUSTED", 402, msg)


# --- Concurrency (412) ---
def stale_version(msg="Expected version does not match current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)

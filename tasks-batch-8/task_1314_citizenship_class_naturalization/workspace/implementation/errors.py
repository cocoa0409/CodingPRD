"""Error types and catalog for the naturalization API."""


class ApiError(Exception):
    def __init__(self, http_status, error_id, message):
        super().__init__(message)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message


def err_invalid_request(message="Request body is malformed or has invalid fields"):
    return ApiError(400, "ERR_INVALID_REQUEST", message)


def err_unauthenticated(message="Missing or invalid authentication headers"):
    return ApiError(401, "ERR_UNAUTHENTICATED", message)


def err_forbidden(message="Role not permitted for this operation"):
    return ApiError(403, "ERR_FORBIDDEN", message)


def err_not_found(message="Referenced resource does not exist"):
    return ApiError(404, "ERR_NOT_FOUND", message)


def err_invalid_state(message="Resource state does not permit the requested transition"):
    return ApiError(409, "ERR_INVALID_STATE", message)


def err_stale_version(message="Expected version does not match the current version"):
    return ApiError(412, "ERR_STALE_VERSION", message)


def conflict(error_id, message):
    return ApiError(409, error_id, message)

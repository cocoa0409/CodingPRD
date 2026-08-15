"""Error classes carrying error_id + http_status from the scaffold catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience factories ------------------------------------------------------

def err_unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Referenced resource id does not exist or is out of parent scope"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Malformed payload"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_state(msg="Resource not in a from-state that allows the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_conflict(error_id, msg=""):
    return ApiError(error_id, 409, msg or error_id)

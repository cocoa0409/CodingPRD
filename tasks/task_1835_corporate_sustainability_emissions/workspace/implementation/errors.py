"""API error type carrying the scaffold error id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


def unauthenticated(msg="Missing or unrecognized X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def cycle_not_collecting(msg="Parent cycle is not in a status that permits this mutation"):
    return ApiError("ERR_CYCLE_NOT_COLLECTING", 409, msg)


def sod(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)

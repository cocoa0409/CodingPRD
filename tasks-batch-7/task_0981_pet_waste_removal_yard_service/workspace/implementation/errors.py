"""Error classes carrying the scaffold-defined error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role lacks permission for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Path id does not resolve"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_ref_not_found(msg="Body FK does not resolve"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 422, msg)


def err_invalid_state(msg="State machine transition invalid from current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_invalid_request(msg="Required field missing / wrong type / malformed body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)

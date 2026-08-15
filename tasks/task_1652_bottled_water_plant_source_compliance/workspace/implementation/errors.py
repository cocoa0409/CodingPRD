"""Error type carrying the scaffold's exact error_id / http_status."""


class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


def err_not_found(what="resource"):
    return ApiError("ERR_NOT_FOUND", f"{what} not found", 404)


def err_invalid_request(msg="malformed request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="resource state does not admit the operation"):
    return ApiError("ERR_INVALID_STATE", msg, 409)

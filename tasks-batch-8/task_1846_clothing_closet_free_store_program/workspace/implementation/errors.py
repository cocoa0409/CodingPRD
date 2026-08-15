"""API error type carrying the scaffold-defined error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def not_found(message="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, message)


def forbidden(message="Role is not permitted to perform this operation"):
    return ApiError("ERR_FORBIDDEN", 403, message)


def invalid_state(message="Resource is not in a state that permits this transition"):
    return ApiError("ERR_INVALID_STATE", 409, message)

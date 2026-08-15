"""Error type carrying the scaffold's error_id / message / http_status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    return ApiError(error_id, message, http_status)


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def not_found(message="Referenced entity does not exist"):
    return ApiError("ERR_NOT_FOUND", message, 404)


def invalid_state(message="Target entity not in expected state for this transition"):
    return ApiError("ERR_INVALID_STATE", message, 409)

"""Error type carrying the scaffold error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def not_found(message="resource not found"):
    return ApiError("ERR_NOT_FOUND", message, 404)


def invalid_state(message="target entity state forbids the requested transition"):
    return ApiError("ERR_INVALID_STATE", message, 409)


def posture_forbidden(message="market posture forbids the operation"):
    return ApiError("ERR_POSTURE_FORBIDDEN", message, 409)


def validation(message):
    return ApiError("ERR_VALIDATION", message, 422)

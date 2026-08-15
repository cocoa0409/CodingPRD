"""API error type carrying the scaffold error id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# Frequently used constructors
def validation(msg):
    return ApiError("ERR_VALIDATION", 400, msg)


def not_found(error_id, msg):
    return ApiError(error_id, 404, msg)


def invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)

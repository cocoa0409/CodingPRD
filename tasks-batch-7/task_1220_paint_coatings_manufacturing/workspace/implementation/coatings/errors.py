"""Error type carrying the scaffold error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, status, error_id, message):
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.message = message


def bad_request(msg):
    return ApiError(400, "ERR_INVALID_REQUEST", msg)


def not_found(msg="Referenced id does not exist"):
    return ApiError(404, "ERR_NOT_FOUND", msg)


def invalid_state(msg):
    return ApiError(409, "ERR_INVALID_STATE", msg)


def unprocessable(error_id, msg):
    return ApiError(422, error_id, msg)


def conflict(error_id, msg):
    return ApiError(409, error_id, msg)

"""Error type carrying the scaffold-defined error_id, HTTP status and message."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def raise_err(error_id, status, message):
    raise ApiError(error_id, status, message)


def invalid_request(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def not_found(message="Path resource does not exist"):
    raise ApiError("ERR_NOT_FOUND", 404, message)


def invalid_state(message):
    raise ApiError("ERR_INVALID_STATE", 409, message)


def referential(message):
    raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, message)

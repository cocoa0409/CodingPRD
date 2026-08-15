"""Error type carrying the scaffold's error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def raise_err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def bad_request(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def invalid_state(msg):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def not_found(error_id, what):
    raise ApiError(error_id, 404, f"{what} not found")

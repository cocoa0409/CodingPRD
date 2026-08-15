"""Error type carrying the scaffold's error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def raise_err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def not_found(what="Resource"):
    raise ApiError("ERR_NOT_FOUND", 404, f"{what} not found")


def invalid_state(msg):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def bad_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)

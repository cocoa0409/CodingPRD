class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def not_found(what="Resource"):
    return ApiError("ERR_NOT_FOUND", 404, f"{what} does not exist")


def invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)

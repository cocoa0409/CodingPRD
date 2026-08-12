"""Error type carrying the scaffold's error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)

"""Error type carrying the scaffold's error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message, http_status):
    raise ApiError(error_id, message, http_status)

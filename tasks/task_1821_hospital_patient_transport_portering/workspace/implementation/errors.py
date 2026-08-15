"""Error types and error-id constants for the Hospital Patient Transport API."""


class ApiError(Exception):
    """Exception carrying an error_id, HTTP status, and human message."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def raise_err(error_id, status, message):
    raise ApiError(error_id, status, message)

"""API error type carrying the scaffold's error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id

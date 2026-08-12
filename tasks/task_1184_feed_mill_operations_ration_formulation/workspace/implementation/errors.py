"""API error type carrying the scaffold-defined error_id and HTTP status."""


class ApiError(Exception):
    """An error that maps directly onto the PRD error envelope."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message

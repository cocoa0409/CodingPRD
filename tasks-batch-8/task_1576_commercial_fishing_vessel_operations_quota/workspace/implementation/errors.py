"""Error type for the Commercial Fishing Quota API."""


class ApiError(Exception):
    """Carries an HTTP status, a machine-readable error_id, and a message."""

    def __init__(self, status, error_id, message):
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.message = message

class ApiError(Exception):
    """API error carrying the scaffold-declared error id, HTTP status and message."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message

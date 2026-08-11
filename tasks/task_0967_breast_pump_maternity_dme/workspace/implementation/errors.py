class ApiError(Exception):
    """Application error carrying the scaffold-declared error_id and HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status

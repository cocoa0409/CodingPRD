class ApiError(Exception):
    """An API error carrying the scaffold-defined error_id and HTTP status."""

    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status

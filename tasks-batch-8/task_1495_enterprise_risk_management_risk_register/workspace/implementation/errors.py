class ApiError(Exception):
    """Carries the PRD error envelope triple: error_id, http status, message."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message

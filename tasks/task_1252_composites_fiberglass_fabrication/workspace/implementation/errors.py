class ApiError(Exception):
    """Carries an error_id, http_status and message through to the envelope."""

    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id

"""API error type. error_id and http_status come from the PRD §5 catalogue."""


class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status

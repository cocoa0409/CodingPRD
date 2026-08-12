"""Error type carrying the scaffold's error_id / message / http_status triple."""


class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status

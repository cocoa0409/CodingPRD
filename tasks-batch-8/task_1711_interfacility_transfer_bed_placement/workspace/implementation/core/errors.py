"""Error carrier: every failure is an ApiError with the PRD's exact error_id,
HTTP status and a human-readable message, rendered by app.py's handler into
the section 2.2 error envelope."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def fail(error_id, message, http_status):
    raise ApiError(error_id, message, http_status)

"""API error type. error_id / http_status values come from the PRD error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err400(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err404(msg):
    return ApiError("ERR_NOT_FOUND", 404, msg)

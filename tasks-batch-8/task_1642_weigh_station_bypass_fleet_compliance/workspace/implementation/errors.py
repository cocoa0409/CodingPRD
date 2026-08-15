"""API error type. error_id and http_status come from the PRD section 5 catalogue."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def bad_request(message, error_id="ERR_INVALID_REQUEST"):
    return ApiError(error_id, 400, message)


def forbidden(message, error_id="ERR_FORBIDDEN_ROLE"):
    return ApiError(error_id, 403, message)


def not_found(error_id, message):
    return ApiError(error_id, 404, message)


def conflict(message, error_id="ERR_INVALID_STATE_TRANSITION"):
    return ApiError(error_id, 409, message)

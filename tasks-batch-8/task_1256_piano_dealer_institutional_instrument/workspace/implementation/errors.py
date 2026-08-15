class ApiError(Exception):
    """Domain error carrying the scaffold error_id, HTTP status, and message."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def invalid(message):
    return ApiError('ERR_INVALID_REQUEST', 400, message)


def not_found(what='resource'):
    return ApiError('ERR_NOT_FOUND', 404, '%s not found' % what)


def forbidden(message):
    return ApiError('ERR_UNAUTHORIZED_ROLE', 403, message)

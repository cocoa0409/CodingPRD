"""Error type carrying the scaffold error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers, or unrecognized role"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Caller role is not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def not_found(msg="Resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_state(msg="Target entity is not in a valid from-state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def already_terminal(msg="Target entity is already in a terminal state and the requested transition is undefined"):
    return ApiError("ERR_ALREADY_TERMINAL", msg, 409)


def stale_version(msg="expected_show_version does not match the show's current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def invalid_request(msg="Required input field missing, malformed, or fails type check"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def biz(error_id, msg):
    """Business-rule failure; all catalogued business errors are HTTP 422."""
    return ApiError(error_id, msg, 422)

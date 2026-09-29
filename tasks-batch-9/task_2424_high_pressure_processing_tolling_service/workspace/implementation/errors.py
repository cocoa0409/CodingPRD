"""Error catalogue (PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def invalid_request(message="Malformed request."):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def unauthenticated(message="Missing or invalid identity headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, message)


def unauthorized(message="The acting role is not permitted on this endpoint."):
    return ApiError("ERR_UNAUTHORIZED", 403, message)


def not_owner(message="The acting customer does not own this resource."):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, message)


def forbidden(error_id, message=None):
    """403 codes other than the two generic auth failures."""
    return ApiError(error_id, 403, message or "Forbidden by a separation rule.")


def not_found(error_id, message=None):
    return ApiError(error_id, 404, message or "Referenced resource does not exist.")


def conflict(error_id, message=None):
    return ApiError(error_id, 409, message or "Conflicting state.")


def unprocessable(error_id, message=None):
    return ApiError(error_id, 422, message or "Business rule violated.")


def precondition(error_id, message=None):
    return ApiError(error_id, 412, message or "Stale version.")

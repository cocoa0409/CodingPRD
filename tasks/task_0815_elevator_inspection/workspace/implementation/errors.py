"""Custom error type carrying an error_id, message, and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience factory helpers -------------------------------------------------

def missing_or_invalid_user_context():
    return ApiError(
        "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
        "X-User-ID and X-User-Role headers are required and the role must be known.",
    )


def insufficient_permissions():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role not permitted for this operation.")


def not_resource_owner():
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                    "Caller does not own the target resource.")


def invalid_request(message="Malformed request body."):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_pagination():
    return ApiError("ERR_INVALID_PAGINATION", 400,
                    "limit or offset is outside the allowed range.")


def not_found(error_id, message=None):
    return ApiError(error_id, 404, message)

"""API error type carrying the scaffold error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role header"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(entity):
    return ApiError("ERR_NOT_FOUND", 404, f"{entity} not found")


def err_validation(msg):
    return ApiError("ERR_VALIDATION", 422, msg)


def err_invalid_state(msg="Resource state does not permit this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)

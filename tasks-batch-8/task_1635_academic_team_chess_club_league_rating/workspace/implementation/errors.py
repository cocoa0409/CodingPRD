"""Error type carrying the scaffold-defined error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


# Convenience constructors (ids from the scaffold error catalog).
def missing_headers():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers are required and must be non-empty")


def insufficient_permissions():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role not permitted on this endpoint")


def forbidden_ownership():
    return ApiError("ERR_FORBIDDEN_RESOURCE_OWNERSHIP", 403,
                    "Actor is outside the ownership scope of this resource")


def not_found(what="resource"):
    return ApiError("ERR_NOT_FOUND", 404, "%s not found" % what)


def stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "expected version does not match the parent's current version")


def invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def state_error(error_id, msg=None):
    return ApiError(error_id, 409, msg or error_id)


def integrity_error(error_id, msg=None):
    return ApiError(error_id, 403, msg or error_id)


def conflict_error(error_id, msg=None):
    return ApiError(error_id, 409, msg or error_id)


def insufficient_funds():
    return ApiError("ERR_INSUFFICIENT_FUNDS", 402,
                    "Charge would drive the club balance below zero")

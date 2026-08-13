"""Error type carrying the scaffold-declared error_id / http_status (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# Convenience constructors — ids and statuses from the scaffold error catalog.
def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def invalid_request(msg="Request body is missing a required field or is malformed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def forbidden(msg="The acting role is not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def ownership_forbidden(msg="The resource is outside the caller's ownership scope"):
    return ApiError("ERR_OWNERSHIP_FORBIDDEN", 403, msg)


def not_found(msg="A path identifier or referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="The current state does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)

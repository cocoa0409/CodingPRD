"""Error type carrying the scaffold-declared error_id / http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# Convenience constructors — ids and statuses from the scaffold error catalog.
def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized_role(msg="Acting role is not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def forbidden_ownership(msg="ClientCoordinator may only act on its own conference group"):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, msg)


def not_found(msg="A path identifier does not reference an existing resource"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Request body is missing a required field or is malformed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def date_range_invalid(msg="Date range is invalid"):
    return ApiError("ERR_DATE_RANGE_INVALID", 400, msg)


def stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="The current state does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)

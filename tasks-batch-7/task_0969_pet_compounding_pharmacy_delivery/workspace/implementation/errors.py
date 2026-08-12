class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


def err(error_id, message, status):
    return ApiError(error_id, message, status)


# Error id constants with their HTTP statuses (from the scaffold error catalog)
def unauthenticated(msg="X-User-Role header missing or not a declared role"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden_role(msg="role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def not_owner(msg="X-User-ID does not own the targeted resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", msg, 403)


def not_found(msg="resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_request(msg="invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def invalid_state(msg="resource is not in a permitted state for this transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)

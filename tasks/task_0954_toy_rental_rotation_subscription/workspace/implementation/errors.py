"""Error type carrying the scaffold error_id / HTTP status pair."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth -----------------------------------------------------------------
def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized_role(msg="Caller role not in the endpoint's roles list."):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def forbidden_ownership(msg="Member caller does not own the target resource."):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, msg)


# --- Existence -------------------------------------------------------------
def not_found(error_id, msg):
    return ApiError(error_id, 404, msg)


# --- Generic ----------------------------------------------------------------
def invalid_state(msg="Target entity is in an illegal state for this transition."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def validation(msg="Malformed request body."):
    return ApiError("ERR_VALIDATION", 400, msg)


def stale_version(msg="Expected version does not match the resource's current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def domain(error_id, http_status, msg):
    return ApiError(error_id, http_status, msg)

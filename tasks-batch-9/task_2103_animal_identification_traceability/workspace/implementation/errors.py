"""Error type + catalogue helpers (PRD 5 error code catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# --- auth / shape ---------------------------------------------------------
def unauthenticated(msg="X-User-ID and X-User-Role headers are required"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="The acting role is not authorised for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def not_resource_owner(msg="The acting principal does not own this resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


def data_access_denied(msg="The producer privacy gate denies this read"):
    return ApiError("ERR_DATA_ACCESS_DENIED", 403, msg)


def segregation_of_duties(msg="The acting user performed the incompatible prior step"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def invalid_request(msg="The request body or query string is malformed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- existence ------------------------------------------------------------
def not_found(error_id, msg=None):
    return ApiError(error_id, 404, msg or "The referenced resource does not exist")


# --- concurrency ----------------------------------------------------------
def stale_version(msg="The supplied expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


# --- state ----------------------------------------------------------------
def invalid_state(msg="The resource's current state does not permit this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg or "The request conflicts with the current state")


def unprocessable(error_id, msg=None):
    return ApiError(error_id, 422, msg or "The request is semantically invalid")

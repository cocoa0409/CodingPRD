"""API error type carrying the scaffold-declared error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Auth ---
def unauthenticated(msg="Missing or invalid X-User-Role or X-User-ID header"):
    return ApiError('ERR_UNAUTHENTICATED', 401, msg)


def forbidden(msg="Role not permitted for this endpoint, or ownership mismatch"):
    return ApiError('ERR_FORBIDDEN', 403, msg)


def not_assigned_judge(msg="Caller is not the judge assigned to this ring slot"):
    return ApiError('ERR_NOT_ASSIGNED_JUDGE', 403, msg)


def segregation(msg="Maker and checker steps must be performed by different users"):
    return ApiError('ERR_SEGREGATION_OF_DUTIES', 403, msg)


# --- Existence / state ---
def not_found(msg="Referenced resource does not exist"):
    return ApiError('ERR_NOT_FOUND', 404, msg)


def invalid_state(msg="Resource is in the wrong state for the requested transition"):
    return ApiError('ERR_INVALID_STATE', 409, msg)


def stale_version(msg="Expected version does not match the current version"):
    return ApiError('ERR_STALE_VERSION', 412, msg)


def posture_forbids(msg="The fair's current posture does not permit this operation"):
    return ApiError('ERR_POSTURE_FORBIDS', 409, msg)


# --- Business errors ---
def invalid_request(msg="Missing required field, invalid enum, or malformed value"):
    return ApiError('ERR_INVALID_REQUEST', 400, msg)


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)

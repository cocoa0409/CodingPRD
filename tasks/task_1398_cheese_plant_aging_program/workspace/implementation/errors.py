"""Error types and the error catalogue (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Convenience raisers -------------------------------------------------------

def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    raise ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="Role not permitted for this endpoint"):
    raise ApiError("ERR_UNAUTHORIZED", 403, msg)


def not_found(msg="Referenced resource id does not exist"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Malformed payload"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def stale_version(msg="expected version does not match the parent's current version"):
    raise ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="Resource not in a state that permits the requested transition"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)

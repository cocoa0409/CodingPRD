"""Error types and helpers. Error IDs and HTTP statuses come from the
SCAFFOLD/PRD error catalogue (section 1.6 / PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(message="Missing or unknown authentication headers"):
    raise ApiError("ERR_UNAUTHENTICATED", 401, message)


def forbidden(message="Role not permitted for this endpoint"):
    raise ApiError("ERR_FORBIDDEN", 403, message)


def not_found(message="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, message)


def bad_request(message="Invalid request"):
    raise ApiError("ERR_INVALID_REQUEST", 422, message)


def stale(message="Expected version does not match current version"):
    raise ApiError("ERR_STALE_VERSION", 412, message)


def invalid_state(message="Resource is not in a legal state for this operation"):
    raise ApiError("ERR_INVALID_STATE", 409, message)


def sod(message="Segregation of duties violation"):
    raise ApiError("ERR_SOD_VIOLATION", 403, message)


def cross_scope(message="Referenced resource does not resolve within the same turnaround"):
    raise ApiError("ERR_CROSS_SCOPE_REFERENCE", 409, message)


def conflict(error_id, message):
    raise ApiError(error_id, 409, message)

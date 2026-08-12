"""Error type carrying the scaffold's error_id / http_status pair."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# Shorthand constructors for every catalogued error.
def unauthenticated(msg="Missing or unrecognized X-User-ID / X-User-Role headers"):
    err("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized_role(msg="Role not permitted for this endpoint"):
    err("ERR_UNAUTHORIZED_ROLE", 403, msg)


def forbidden_identity(msg="X-User-ID does not match the required owner"):
    err("ERR_FORBIDDEN_IDENTITY", 403, msg)


def not_found(msg="Referenced resource does not exist"):
    err("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Missing or malformed field"):
    err("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg="Resource state does not allow this transition"):
    err("ERR_INVALID_STATE", 409, msg)


def already_terminal(msg="Resource is in a terminal state"):
    err("ERR_ALREADY_TERMINAL", 409, msg)


def stale_version(msg="expected_site_version does not match current Site.version"):
    err("ERR_STALE_VERSION", 412, msg)

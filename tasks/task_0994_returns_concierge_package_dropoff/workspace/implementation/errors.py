"""API error type carrying the scaffold-defined error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


# Shorthand raisers for the most common failures.
def bad_request(msg="Malformed body or missing required field"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def enum_invalid(msg="Enum field carries an undeclared member"):
    raise ApiError("ERR_ENUM_INVALID", 400, msg)


def not_found(msg="Referenced resource does not exist"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Resource not in a valid from-state for the requested transition"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def already_terminal(msg="Resource is in a terminal state; no further transitions"):
    raise ApiError("ERR_ALREADY_TERMINAL", 409, msg)


def ownership(msg="Entity-backed caller does not own the target resource"):
    raise ApiError("ERR_OWNERSHIP_MISMATCH", 403, msg)

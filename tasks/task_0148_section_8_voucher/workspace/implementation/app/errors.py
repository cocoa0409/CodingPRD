"""Domain exception class carrying error_id and HTTP status."""


class APIError(Exception):
    """Raised by services / routes to signal a structured failure."""

    def __init__(self, error_id: str, http_status: int, message: str = "") -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Convenience constructors so call sites stay readable.

def auth_required(message: str = "Missing X-User-ID or X-User-Role header") -> APIError:
    return APIError("ERR_AUTH_REQUIRED", 401, message)


def forbidden_role(message: str = "Role not permitted for this endpoint") -> APIError:
    return APIError("ERR_FORBIDDEN_ROLE", 403, message)


def not_found(message: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", 404, message)


def fk_not_found(message: str = "Foreign-key referenced resource not found") -> APIError:
    return APIError("ERR_FK_NOT_FOUND", 422, message)


def invalid_state(message: str = "Resource not in a valid state") -> APIError:
    return APIError("ERR_INVALID_STATE", 409, message)


def validation(message: str = "Validation failure") -> APIError:
    return APIError("ERR_VALIDATION", 422, message)

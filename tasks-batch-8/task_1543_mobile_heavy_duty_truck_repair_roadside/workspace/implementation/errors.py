"""Error classes and error ID constants for the roadside API."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- catalog (SCAFFOLD 1.6 / PRD section 5) ---
def err_unauthenticated(msg="Missing or blank X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized_role(msg="Role not in the endpoint's declared roles"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", msg, 403)


def err_forbidden_ownership(msg="Actor is not the owning technician / fleet manager of the target resource"):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", msg, 403)


def err_not_found(msg="Resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_validation(msg="Request shape violation"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_invalid_enum(msg="Enum field carries an undeclared member"):
    return ApiError("ERR_INVALID_ENUM", msg, 400)


def err_invalid_state(msg="Target entity is not in a from-state of the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_call_terminal(msg="Action attempted on a CANCELLED service call"):
    return ApiError("ERR_CALL_ALREADY_TERMINAL", msg, 409)


def err_stale_version(msg="expected_service_call_version does not match the call's current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)

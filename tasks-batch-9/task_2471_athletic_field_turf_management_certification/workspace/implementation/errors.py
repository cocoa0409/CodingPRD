"""Error catalogue (PRD section 5) expressed as a single raisable exception type."""


class ApiError(Exception):
    """Carries the error_id / http_status pair from the PRD error catalogue."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------- helpers
def missing_auth():
    return ApiError(
        "ERR_MISSING_AUTH_HEADERS", 401,
        "X-User-ID and X-User-Role headers are both required and must be non-empty.")


def unknown_role(value):
    return ApiError("ERR_UNKNOWN_ROLE", 401,
                    "X-User-Role '%s' is not one of the five declared roles." % value)


def role_identity_mismatch():
    return ApiError(
        "ERR_ROLE_IDENTITY_MISMATCH", 403,
        "X-User-ID does not resolve to an ACTIVE staff member holding the claimed role.")


def unauthorized(role, path):
    return ApiError("ERR_UNAUTHORIZED", 403,
                    "Role %s is not authorised for %s." % (role, path))


def invalid_request(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def not_found(error_id, what):
    return ApiError(error_id, 404, "%s could not be found." % what)

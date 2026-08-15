"""Error types and the scaffold's error catalog (ids + HTTP statuses)."""


class ApiError(Exception):
    """Carries error_id, HTTP status and a human-readable message."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# Error catalog (SCAFFOLD.yaml `errors` / PRD section 5)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCE_NOT_FOUND = ("ERR_REFERENCE_NOT_FOUND", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_CODE_SEVERITY_TOO_LOW = ("ERR_CODE_SEVERITY_TOO_LOW", 422)
ERR_YEAR_OUT_OF_RANGE = ("ERR_YEAR_OUT_OF_RANGE", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_REFERENTIAL_CONFLICT = ("ERR_REFERENTIAL_CONFLICT", 409)
ERR_PRECONDITION_UNMET = ("ERR_PRECONDITION_UNMET", 409)
ERR_INVALID_BUDGET = ("ERR_INVALID_BUDGET", 422)


def raise_error(catalog_entry, message):
    error_id, status = catalog_entry
    raise ApiError(error_id, status, message)

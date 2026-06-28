"""Error classes and error-id constants (scaffold §1.6 / PRD §5)."""


class ApiError(Exception):
    """Carries error_id, message, and http_status for the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog — exact ids and HTTP statuses from scaffold §1.6 / PRD §5.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_CASE_OWNER = ("ERR_NOT_CASE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_CASE_VERSION = ("ERR_STALE_CASE_VERSION", 412)
ERR_STALE_MACHINE_VERSION = ("ERR_STALE_MACHINE_VERSION", 412)
ERR_MATERIAL_INACTIVE = ("ERR_MATERIAL_INACTIVE", 422)
ERR_MACHINE_CAPABILITY_MISMATCH = ("ERR_MACHINE_CAPABILITY_MISMATCH", 422)
ERR_EMPTY_FABRICATION = ("ERR_EMPTY_FABRICATION", 422)
ERR_MAX_REVISIONS_EXCEEDED = ("ERR_MAX_REVISIONS_EXCEEDED", 422)
ERR_MACHINE_DOUBLE_BOOKED = ("ERR_MACHINE_DOUBLE_BOOKED", 409)
ERR_ROUTE_WINDOW_CONFLICT = ("ERR_ROUTE_WINDOW_CONFLICT", 409)
ERR_ROUTE_AT_CAPACITY = ("ERR_ROUTE_AT_CAPACITY", 422)
ERR_UNIT_NOT_WARRANTABLE = ("ERR_UNIT_NOT_WARRANTABLE", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_VALIDATION = ("ERR_VALIDATION", 422)
ERR_PAGINATION_INVALID = ("ERR_PAGINATION_INVALID", 400)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)

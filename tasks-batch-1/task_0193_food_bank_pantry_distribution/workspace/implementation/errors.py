"""Error catalog and the ApiError exception carrying error_id + http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# §1.6 Error Code Catalog
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_AGENCY_SCOPE_VIOLATION = ("ERR_AGENCY_SCOPE_VIOLATION", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_COLD_CHAIN_MISMATCH = ("ERR_COLD_CHAIN_MISMATCH", 422)
ERR_COLD_STORAGE_CAPACITY_EXCEEDED = ("ERR_COLD_STORAGE_CAPACITY_EXCEEDED", 409)
ERR_HOUSEHOLD_NOT_CERTIFIED = ("ERR_HOUSEHOLD_NOT_CERTIFIED", 409)
ERR_AGENCY_SUSPENDED = ("ERR_AGENCY_SUSPENDED", 409)
ERR_CYCLE_NOT_OPEN = ("ERR_CYCLE_NOT_OPEN", 409)
ERR_OVER_DISTRIBUTION = ("ERR_OVER_DISTRIBUTION", 422)
ERR_FAIR_SHARE_EXCEEDED = ("ERR_FAIR_SHARE_EXCEEDED", 409)
ERR_STALE_LOT_VERSION = ("ERR_STALE_LOT_VERSION", 412)
ERR_VALIDATION_PAGINATION = ("ERR_VALIDATION_PAGINATION", 422)


def err(code_tuple, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    return ApiError(code_tuple[0], code_tuple[1], message)

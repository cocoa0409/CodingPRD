"""Error classes and canonical error catalogue (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical error_id -> http_status
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_ROUTE_LOCKED = ("ERR_ROUTE_LOCKED", 409)
ERR_VACCINATION_REQUIRED = ("ERR_VACCINATION_REQUIRED", 422)
ERR_NO_QUALIFIED_GROOMER = ("ERR_NO_QUALIFIED_GROOMER", 422)
ERR_ZIP_NOT_COVERED = ("ERR_ZIP_NOT_COVERED", 422)
ERR_SLOT_OVERLAP = ("ERR_SLOT_OVERLAP", 409)
ERR_VAN_STOPS_FULL = ("ERR_VAN_STOPS_FULL", 409)
ERR_ACCOUNT_SUSPENDED = ("ERR_ACCOUNT_SUSPENDED", 422)
ERR_ROUTE_CAPACITY_EXCEEDED = ("ERR_ROUTE_CAPACITY_EXCEEDED", 409)
ERR_ADDON_NOT_ALLOWED = ("ERR_ADDON_NOT_ALLOWED", 422)
ERR_STALE_ROUTE_VERSION = ("ERR_STALE_ROUTE_VERSION", 412)
ERR_SHOW_CUT_UNSUPPORTED = ("ERR_SHOW_CUT_UNSUPPORTED", 422)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def err(catalog_tuple, message=None):
    error_id, http_status = catalog_tuple
    return ApiError(error_id, http_status, message)

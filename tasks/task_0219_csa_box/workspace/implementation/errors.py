"""Error classes and error-id constants for the CSA Box API.

Every error_id and HTTP status below is read verbatim from SCAFFOLD.yaml §1.6
and PRD §5 (Error Code Catalogue).
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# §1.6 / PRD §5 error catalog
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_SEASON_MISMATCH = ("ERR_SEASON_MISMATCH", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_SIGNUP_CLOSED = ("ERR_SIGNUP_CLOSED", 409)
ERR_HOLD_WINDOW_PASSED = ("ERR_HOLD_WINDOW_PASSED", 409)
ERR_INVALID_SWAP_TARGET = ("ERR_INVALID_SWAP_TARGET", 422)
ERR_OFFER_EXPIRED = ("ERR_OFFER_EXPIRED", 409)
ERR_ADDON_SUPPLY_EXHAUSTED = ("ERR_ADDON_SUPPLY_EXHAUSTED", 409)
ERR_NOT_WORKING_SHARE = ("ERR_NOT_WORKING_SHARE", 409)
ERR_SITE_CAPACITY_FULL = ("ERR_SITE_CAPACITY_FULL", 409)
ERR_SEASON_CAPACITY_FULL = ("ERR_SEASON_CAPACITY_FULL", 409)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_DUPLICATE_EMAIL = ("ERR_DUPLICATE_EMAIL", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_VALIDATION_PAGINATION = ("ERR_VALIDATION_PAGINATION", 422)


def err(spec, message=None):
    """Build an ApiError from one of the (id, status) tuples above."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)

"""Error classes and error-id constants.

Every error_id and its HTTP status comes from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id, http_status) from PRD §5 Error Code Catalogue
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_DUPLICATE_CODE = ("ERR_DUPLICATE_CODE", 409)
ERR_SPLIT_TOTAL_INVALID = ("ERR_SPLIT_TOTAL_INVALID", 422)
ERR_SHARES_LOCKED = ("ERR_SHARES_LOCKED", 409)
ERR_SHARES_NOT_LOCKED = ("ERR_SHARES_NOT_LOCKED", 409)
ERR_RIGHTS_NOT_AVAILABLE = ("ERR_RIGHTS_NOT_AVAILABLE", 422)
ERR_NO_OPEN_STATEMENT = ("ERR_NO_OPEN_STATEMENT", 409)
ERR_WINDOW_OVERLAP = ("ERR_WINDOW_OVERLAP", 409)
ERR_STATEMENT_PERIOD_OVERLAP = ("ERR_STATEMENT_PERIOD_OVERLAP", 409)
ERR_UNALLOCATED_USAGE_IN_PERIOD = ("ERR_UNALLOCATED_USAGE_IN_PERIOD", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_PAYOUT_EXISTS = ("ERR_PAYOUT_EXISTS", 409)
ERR_RIGHTSHOLDER_SUSPENDED = ("ERR_RIGHTSHOLDER_SUSPENDED", 409)
ERR_NOTHING_PAYABLE = ("ERR_NOTHING_PAYABLE", 409)


def fail(err, message=None):
    """Raise an ApiError from one of the (error_id, http) tuples above."""
    error_id, http_status = err
    raise ApiError(error_id, http_status, message)

"""Error catalogue and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (PRD §5)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_DUPLICATE_ISBN = ("ERR_DUPLICATE_ISBN", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_NOT_LOCAL_AUTHOR = ("ERR_NOT_LOCAL_AUTHOR", 422)
ERR_TITLE_NOT_RETURNABLE = ("ERR_TITLE_NOT_RETURNABLE", 422)
ERR_TITLE_NOT_POD_ELIGIBLE = ("ERR_TITLE_NOT_POD_ELIGIBLE", 422)
ERR_REVISION_LIMIT = ("ERR_REVISION_LIMIT", 422)
ERR_EVENT_PAST = ("ERR_EVENT_PAST", 422)
ERR_INSUFFICIENT_STOCK = ("ERR_INSUFFICIENT_STOCK", 422)
ERR_EVENT_SOLD_OUT = ("ERR_EVENT_SOLD_OUT", 422)
ERR_INSUFFICIENT_CREDIT = ("ERR_INSUFFICIENT_CREDIT", 422)
ERR_EMPTY_TRANSACTION = ("ERR_EMPTY_TRANSACTION", 422)
ERR_MEMBER_SUSPENDED = ("ERR_MEMBER_SUSPENDED", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) spec tuple."""
    return ApiError(spec[0], spec[1], message)

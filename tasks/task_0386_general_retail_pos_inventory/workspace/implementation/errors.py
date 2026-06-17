"""Error catalogue (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue — error_id -> HTTP status
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCE_NOT_FOUND = ("ERR_REFERENCE_NOT_FOUND", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_DUPLICATE_RESOURCE = ("ERR_DUPLICATE_RESOURCE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_DRAWER_NOT_OPEN = ("ERR_DRAWER_NOT_OPEN", 409)
ERR_INVALID_RETURN_REFERENCE = ("ERR_INVALID_RETURN_REFERENCE", 422)
ERR_PROMO_NOT_APPLICABLE = ("ERR_PROMO_NOT_APPLICABLE", 422)
ERR_PROMO_NOT_STACKABLE = ("ERR_PROMO_NOT_STACKABLE", 422)
ERR_INSUFFICIENT_POINTS = ("ERR_INSUFFICIENT_POINTS", 422)
ERR_INSUFFICIENT_STOCK = ("ERR_INSUFFICIENT_STOCK", 409)
ERR_OVERTENDER = ("ERR_OVERTENDER", 422)
ERR_COUNT_STALE = ("ERR_COUNT_STALE", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_LAYAWAY_NOT_DELINQUENT = ("ERR_LAYAWAY_NOT_DELINQUENT", 409)


def err(code_tuple, message=None):
    error_id, http_status = code_tuple
    return ApiError(error_id, http_status, message)
